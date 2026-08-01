"""
Interaction history — the worker-facing audit trail.

Powers the mobile app's History tab and satisfies system_prompt.md §9.3's
"every agent action logged with timestamp". Recording is best-effort and never
raises into a caller: a failure to write the history row must not turn a
successful scan into a failed request.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from auth import CurrentUser, get_current_user_optional
from db import async_session, get_db
from models.interaction import Interaction

router = APIRouter(prefix="/api/v1/interactions", tags=["Interaction History"])

VALID_KINDS = {"scan", "voice", "measurement", "drawing_check", "compliance"}


# ---------------------------------------------------------------------------
# Recording helper — called by the agent routes, not by clients
# ---------------------------------------------------------------------------

async def record_interaction(
    kind: str,
    worker_id: Optional[str] = None,
    zone_code: Optional[str] = None,
    query: Optional[str] = None,
    result: Optional[str] = None,
    verdict: Optional[str] = None,
    severity: Optional[str] = None,
    confidence: Optional[float] = None,
    agent_chain: Optional[str] = None,
    latency_ms: Optional[float] = None,
    evidence_ref: Optional[str] = None,
    project_id: str = "default-project",
) -> Optional[str]:
    """Append one interaction. Returns its id, or None if the write failed.

    Never raises — see the module docstring. Callers should not await this in a
    way that blocks their response if it can be avoided.
    """
    try:
        async with async_session() as session:
            row = Interaction(
                project_id=project_id,
                worker_id=worker_id,
                zone_code=zone_code,
                kind=kind if kind in VALID_KINDS else "scan",
                # Truncate rather than reject: a 4KB VLM description should be
                # trimmed for a history feed, not cause the write to fail.
                query=(query or "")[:2000] or None,
                result=(result or "")[:4000] or None,
                verdict=verdict,
                severity=severity,
                confidence=confidence,
                agent_chain=agent_chain,
                latency_ms=latency_ms,
                evidence_ref=evidence_ref,
            )
            session.add(row)
            await session.commit()
            return row.id
    except Exception as e:
        print(f"[INTERACTIONS] failed to record {kind}: {e}")
        return None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class InteractionOut(BaseModel):
    id: str
    kind: str
    query: Optional[str] = None
    result: Optional[str] = None
    verdict: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[float] = None
    zone_code: Optional[str] = None
    worker_id: Optional[str] = None
    agent_chain: Optional[str] = None
    latency_ms: Optional[float] = None
    created_at: Optional[str] = None


@router.get("")
async def list_interactions(
    worker_id: Optional[str] = Query(None, description="filter to one worker"),
    kind: Optional[str] = Query(None, description="scan | voice | measurement | drawing_check | compliance"),
    zone_code: Optional[str] = None,
    project_id: str = "default-project",
    limit: int = Query(50, ge=1, le=200),
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 90),
    user: Optional[CurrentUser] = Depends(get_current_user_optional),
):
    """Most recent interactions first.

    A logged-in worker sees only their own history unless they explicitly ask
    for another worker's and hold a role that can. Engineers and above see
    everything by default, which is what the dashboard needs.
    """
    effective_worker = worker_id
    if user is not None and user.role == "worker" and not worker_id:
        effective_worker = user.id

    try:
        async with async_session() as session:
            stmt = select(Interaction).where(Interaction.project_id == project_id)
            if effective_worker:
                stmt = stmt.where(Interaction.worker_id == effective_worker)
            if kind:
                stmt = stmt.where(Interaction.kind == kind)
            if zone_code:
                stmt = stmt.where(Interaction.zone_code == zone_code)
            if since_hours:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
                stmt = stmt.where(Interaction.created_at >= cutoff)
            stmt = stmt.order_by(Interaction.created_at.desc()).limit(limit)

            rows = (await session.execute(stmt)).scalars().all()

        return {
            "status": "success",
            "count": len(rows),
            "data": [
                InteractionOut(
                    id=r.id, kind=r.kind, query=r.query, result=r.result,
                    verdict=r.verdict, severity=r.severity, confidence=r.confidence,
                    zone_code=r.zone_code, worker_id=r.worker_id,
                    agent_chain=r.agent_chain, latency_ms=r.latency_ms,
                    created_at=r.created_at.isoformat() if r.created_at else None,
                ).model_dump()
                for r in rows
            ],
        }
    except Exception as e:
        # Degrade like the other read paths: an empty, clearly-labelled feed
        # beats a red error screen on the worker's phone.
        print(f"[INTERACTIONS] list failed: {e}")
        return {"status": "degraded", "count": 0, "data": [],
                "error": f"interaction history unavailable: {e}"}


class RecordRequest(BaseModel):
    kind: str = Field(..., description="scan | voice | measurement | drawing_check | compliance")
    worker_id: Optional[str] = None
    zone_code: Optional[str] = None
    query: Optional[str] = None
    result: Optional[str] = None
    verdict: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[float] = None
    agent_chain: Optional[str] = None
    latency_ms: Optional[float] = None
    project_id: str = "default-project"


@router.post("")
async def create_interaction(req: RecordRequest,
                             user: Optional[CurrentUser] = Depends(get_current_user_optional)):
    """Client-side recording, for interactions the backend can't see itself —
    e.g. an offline scan the phone processed on-device and is now syncing."""
    interaction_id = await record_interaction(
        kind=req.kind,
        worker_id=req.worker_id or (user.id if user else None),
        zone_code=req.zone_code, query=req.query, result=req.result,
        verdict=req.verdict, severity=req.severity, confidence=req.confidence,
        agent_chain=req.agent_chain, latency_ms=req.latency_ms,
        project_id=req.project_id,
    )
    if interaction_id is None:
        return {"status": "degraded", "id": None,
                "error": "could not persist interaction"}
    return {"status": "success", "id": interaction_id}


@router.get("/stats")
async def interaction_stats(project_id: str = "default-project",
                            since_hours: int = Query(24, ge=1, le=24 * 90)):
    """Counts by kind and verdict — real numbers for the dashboard activity row."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        async with async_session() as session:
            rows = (await session.execute(
                select(Interaction).where(Interaction.project_id == project_id,
                                          Interaction.created_at >= cutoff)
            )).scalars().all()

        by_kind: dict[str, int] = {}
        by_verdict: dict[str, int] = {}
        latencies = []
        for r in rows:
            by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
            if r.verdict:
                by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
            if r.latency_ms:
                latencies.append(r.latency_ms)

        return {
            "status": "success",
            "window_hours": since_hours,
            "total": len(rows),
            "by_kind": by_kind,
            "by_verdict": by_verdict,
            "mean_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        }
    except Exception as e:
        print(f"[INTERACTIONS] stats failed: {e}")
        return {"status": "degraded", "total": 0, "by_kind": {}, "by_verdict": {},
                "error": str(e)}
