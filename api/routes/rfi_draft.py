"""
Agent 6 — RFI Drafter.

Takes a real detected deviation and drafts the RFI an engineer would otherwise
write by hand: subject, location, the question, and the specification clauses it
rests on. The clauses are RETRIEVED, not generated — see _cite() below.

This replaces a hardcoded modal on the dashboard that rendered the same static
paragraph (about HVAC ductwork and W12x26 beams) for every issue, regardless of
what had actually been detected, and whose "Send to Procore" button only closed
the dialog.

Two honesty constraints, both load-bearing for a system whose entire value
proposition is that its paperwork is defensible:

  1. Citations come from the Qdrant spec index. If retrieval returns nothing,
     the draft says so and cites nothing. A fabricated clause reference in a
     filed RFI is worse than no RFI.
  2. Submission does not claim to reach Procore. There is no Procore
     integration in this system, so /submit records the draft locally and says
     exactly that.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from auth import CurrentUser, get_current_user_optional
from db import async_session
from routes.interactions import record_interaction

router = APIRouter(prefix="/api/v1/rfi", tags=["RFI Drafter (Agent 6)"])


class DraftRequest(BaseModel):
    """Either pass an issue_id to draft from a stored deviation, or supply the
    fields directly (for a predicted RFI that has no FieldIssue row yet)."""
    issue_id: Optional[str] = None
    project_id: str = "default-project"
    zone_id: Optional[str] = None
    title: Optional[str] = None
    asset_type: Optional[str] = None
    measured_value: Optional[str] = None
    expected_value: Optional[str] = None
    deviation_pct: Optional[float] = None
    severity: Optional[str] = None
    worker_id: Optional[str] = None
    extra_context: Optional[str] = Field(
        None, description="anything the engineer wants the draft to address")


class Citation(BaseModel):
    source: str
    excerpt: str
    score: float


# Cosine-similarity floor for citing a passage.
#
# Retrieval always returns its nearest neighbours, however far away they are. On
# an index holding only OSHA fall-protection and scaffold documents, a
# rebar-spacing query still comes back with scaffold ladder-rung passages — real
# text, genuinely retrieved, and irrelevant to the deviation. Printing those
# under "Specification basis" asserts they govern the item.
#
# The threshold is measured, not guessed. Against this project's index with
# BAAI/bge-small-en-v1.5:
#
#     on-topic  ("fall protection guardrail height")   0.83 - 0.85
#     off-topic ("rebar spacing tolerance ACI 318")    0.64 - 0.69
#     nonsense  ("banana smoothie purple elephant")    0.50
#
# BGE similarities are compressed — unrelated text still scores ~0.5, so a naive
# low floor admits everything. 0.78 sits in the gap between the on-topic and
# off-topic clusters.
#
# Consequence worth understanding: a rebar RFI now cites NOTHING, because no
# rebar specification has been ingested. That is the correct answer. To make it
# cite properly, ingest the governing spec (ACI 318 / IS 456) via
# POST /api/v1/memory/index. Re-measure this floor if the embedding model changes.
CITATION_MIN_SCORE = float(os.getenv("RFI_CITATION_MIN_SCORE", "0.78"))


class DraftResponse(BaseModel):
    draft_id: str
    subject: str
    location: str
    impact: str
    body: str
    citations: list[Citation]
    grounded: bool
    generated_at: str
    generator: str
    warnings: list[str] = []


async def _load_issue(issue_id: str) -> Optional[dict]:
    from models.issues import FieldIssue
    try:
        async with async_session() as s:
            row = (await s.execute(
                select(FieldIssue).where(FieldIssue.id == issue_id))).scalars().first()
            if row is None:
                return None
            return {
                "zone_code": row.zone_code,
                "issue_type": row.issue_type,
                "severity": row.severity,
                "description": row.description,
                "measured_value": row.measured_value,
                "expected_value": row.expected_value,
                "deviation_pct": float(row.deviation_pct) if row.deviation_pct is not None else None,
                "worker_id": row.worker_id,
                "drawing_ref": row.drawing_ref,
            }
    except Exception as e:
        print(f"[RFI-DRAFT] could not load issue {issue_id}: {e}")
        return None


async def _cite(query: str, project_id: str, top_k: int = 3) -> list[Citation]:
    """Retrieve real spec passages. Returns [] rather than raising — a draft
    with no citations is valid and clearly labelled; an invented one is not."""
    try:
        from agents.memory.retriever import QdrantRetrieval
        # Over-fetch, then dedupe. Chunked PDFs produce heavily overlapping
        # passages, so a top-3 search routinely returned the SAME paragraph
        # three times — which looked like three independent sources backing the
        # RFI when it was one.
        results = await QdrantRetrieval().search(query, project_id, top_k=top_k * 4)
        out: list[Citation] = []
        seen: set[str] = set()
        for r in results:
            if (r.score or 0.0) < CITATION_MIN_SCORE:
                continue                      # too weak to be the governing clause
            text = " ".join((r.text or "").split())
            if len(text) < 40:
                continue
            # Fingerprint on the opening of the passage: near-duplicate chunks
            # share a prefix even when their tails differ.
            key = text[:120].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(Citation(source=r.source or "project document",
                                excerpt=text[:400], score=round(r.score, 4)))
            if len(out) >= top_k:
                break
        return out
    except Exception as e:
        print(f"[RFI-DRAFT] spec retrieval unavailable: {e}")
        return []


def _fallback_body(ctx: dict, citations: list[Citation]) -> str:
    """Deterministic draft used when the LLM is unavailable.

    Deliberately terse and factual: it restates only what was measured and asks
    the one question that follows from it. No invented site detail.
    """
    lines = [
        f"A deviation was detected during automated inspection of "
        f"{ctx.get('asset_type') or ctx.get('issue_type') or 'the works'} in "
        f"{ctx.get('zone') or 'the recorded zone'}.",
        "",
    ]
    if ctx.get("measured") and ctx.get("expected"):
        lines.append(f"Measured: {ctx['measured']}    Specified: {ctx['expected']}")
    if ctx.get("deviation_pct") is not None:
        lines.append(f"Deviation: {ctx['deviation_pct']:.1f}% outside specification.")
    lines += [
        "",
        "Please advise:",
        "1. Whether the as-built condition can be accepted, or correction is required.",
        "2. If correction is required, the approved remediation method and sequence.",
        "",
    ]
    if citations:
        lines.append("Referenced specifications:")
        lines += [f"  - {c.source}" for c in citations]
    else:
        lines.append("No specification passage was retrieved for this item; the "
                     "governing clause needs to be confirmed by the engineer.")
    return "\n".join(lines)


@router.post("/draft", response_model=DraftResponse)
async def draft_rfi(req: DraftRequest,
                    user: Optional[CurrentUser] = Depends(get_current_user_optional)):
    warnings: list[str] = []

    ctx: dict = {
        "zone": req.zone_id,
        "issue_type": req.title,
        "asset_type": req.asset_type,
        "measured": req.measured_value,
        "expected": req.expected_value,
        "deviation_pct": req.deviation_pct,
        "severity": req.severity,
        "worker_id": req.worker_id,
        "description": None,
        "drawing_ref": None,
    }

    if req.issue_id:
        stored = await _load_issue(req.issue_id)
        if stored is None:
            warnings.append(f"issue {req.issue_id} not found — drafted from the "
                            f"supplied fields only")
        else:
            # Stored values win: they are what the agents actually recorded.
            ctx.update({
                "zone": stored["zone_code"] or ctx["zone"],
                "issue_type": stored["issue_type"] or ctx["issue_type"],
                "measured": stored["measured_value"] or ctx["measured"],
                "expected": stored["expected_value"] or ctx["expected"],
                "deviation_pct": stored["deviation_pct"] if stored["deviation_pct"] is not None else ctx["deviation_pct"],
                "severity": stored["severity"] or ctx["severity"],
                "worker_id": stored["worker_id"] or ctx["worker_id"],
                "description": stored["description"],
                "drawing_ref": stored["drawing_ref"],
            })

    if not ctx["zone"] and not ctx["issue_type"]:
        raise HTTPException(400, "provide issue_id, or at least zone_id and title")

    # --- Agent 7: retrieve the governing specification -----------------------
    retrieval_query = " ".join(str(v) for v in
                               [ctx["issue_type"], ctx["asset_type"], "specification tolerance requirement"]
                               if v)
    citations = await _cite(retrieval_query, req.project_id)
    if not citations:
        warnings.append("no specification passage retrieved — draft cites nothing "
                        "and flags the clause as unconfirmed")

    subject = (f"{ctx['issue_type'] or 'Deviation'} — {ctx['zone'] or 'zone unspecified'}")
    impact_map = {"critical": "Critical (work stopped)", "high": "High (schedule at risk)",
                  "medium": "Medium", "low": "Low"}
    impact = impact_map.get((ctx["severity"] or "").lower(), "To be assessed")

    # --- draft the prose ----------------------------------------------------
    body = ""
    generator = "template"
    try:
        from utils.llm_client import get_llm_response

        spec_block = "\n\n".join(f"[{c.source}] {c.excerpt}" for c in citations) \
            or "(no specification passage retrieved)"

        system_prompt = """
You draft Requests For Information for a construction site. Write the body of one RFI.

Rules, all mandatory:
- Use ONLY the measured values and specification passages given to you.
- Do NOT invent a drawing number, clause number, beam designation, dimension,
  date, or person. If the governing clause was not supplied, say it must be
  confirmed by the engineer.
- Do not reference anything not present in the context (no HVAC, no anchors, no
  lanyards, unless they appear in the context).
- Be specific and short: state the observation, then ask 2-3 numbered questions
  an engineer can answer.
- Plain text, no markdown, no salutation, no signature.
"""
        user_prompt = f"""
Zone: {ctx['zone']}
Element: {ctx['issue_type']} {f"({ctx['asset_type']})" if ctx['asset_type'] else ''}
Measured value: {ctx['measured'] or 'not recorded'}
Specified value: {ctx['expected'] or 'not recorded'}
Deviation: {f"{ctx['deviation_pct']:.1f}%" if ctx['deviation_pct'] is not None else 'not computed'}
Severity: {ctx['severity'] or 'unclassified'}
Detector note: {ctx['description'] or 'none'}
Drawing reference on record: {ctx['drawing_ref'] or 'none'}
Engineer's extra context: {req.extra_context or 'none'}

Specification passages retrieved from the project index:
{spec_block}
"""
        body = (get_llm_response(system_prompt, user_prompt, temperature=0.2,
                                 zone_id=ctx["zone"] or "unknown",
                                 # Prose, not JSON. Without this the client
                                 # forces structured output and this branch
                                 # rejected its own result every time.
                                 json_mode=False) or "").strip()
        # The LLM client falls back to an RFI-shaped JSON mock on failure; that
        # is not prose, so reject it rather than showing JSON to an engineer.
        if not body or body.lstrip().startswith("{"):
            raise ValueError("LLM returned no usable prose")
        generator = f"llm:{os.getenv('LLM_BACKEND', 'unknown')}"
    except Exception as e:
        warnings.append(f"LLM drafting unavailable ({e}) — used the deterministic template")
        body = _fallback_body(ctx, citations)

    draft_id = f"RFI-D-{uuid.uuid4().hex[:8].upper()}"

    await record_interaction(
        kind="compliance",
        worker_id=ctx["worker_id"],
        zone_code=ctx["zone"],
        project_id=req.project_id,
        query=f"Draft RFI for {subject}",
        result=f"{draft_id} drafted ({generator}, {len(citations)} citation(s))",
        severity=ctx["severity"],
        agent_chain="A6:RFI-Drafter -> A7:Knowledge(RAG)",
    )

    return DraftResponse(
        draft_id=draft_id,
        subject=subject,
        location=ctx["zone"] or "unspecified",
        impact=impact,
        body=body,
        citations=citations,
        grounded=bool(citations),
        generated_at=datetime.now(timezone.utc).isoformat(),
        generator=generator,
        warnings=warnings,
    )


class SubmitRequest(BaseModel):
    draft_id: str
    subject: str
    body: str
    zone_id: Optional[str] = None
    issue_id: Optional[str] = None
    project_id: str = "default-project"
    approved_by: Optional[str] = None


@router.post("/draft/submit")
async def submit_rfi(req: SubmitRequest,
                     user: Optional[CurrentUser] = Depends(get_current_user_optional)):
    """Record an approved RFI draft.

    Explicitly does NOT claim to have sent anything to Procore or BIM 360 —
    there is no such integration in this system. The dashboard button used to
    read "Send to Procore" and merely closed the dialog, which would be a
    straightforwardly false claim in front of anyone who asked what it did.
    """
    approver = req.approved_by or (user.email if user else None) or "unattributed"

    interaction_id = await record_interaction(
        kind="compliance",
        zone_code=req.zone_id,
        project_id=req.project_id,
        query=f"RFI approved: {req.subject}",
        result=req.body[:3000],
        verdict="INFO",
        agent_chain="A6:RFI-Drafter -> A9:Notification",
    )

    # Note it on the originating issue so the audit trail links draft to source.
    linked = False
    if req.issue_id:
        try:
            from models.issues import FieldIssue
            async with async_session() as s:
                row = (await s.execute(
                    select(FieldIssue).where(FieldIssue.id == req.issue_id))).scalars().first()
                if row is not None:
                    note = f"RFI {req.draft_id} approved by {approver}"
                    row.resolution_note = (
                        f"{row.resolution_note}\n{note}" if row.resolution_note else note)
                    await s.commit()
                    linked = True
        except Exception as e:
            print(f"[RFI-DRAFT] could not annotate issue {req.issue_id}: {e}")

    return {
        "status": "recorded",
        "draft_id": req.draft_id,
        "approved_by": approver,
        "interaction_id": interaction_id,
        "linked_to_issue": linked,
        "external_delivery": {
            "delivered": False,
            "reason": "No Procore / Autodesk BIM 360 integration is configured. "
                      "The RFI is recorded in FieldPilot's audit trail and is "
                      "available via GET /api/v1/interactions. Wiring an ERP "
                      "connector is roadmap work, not a configuration switch.",
        },
    }
