import json
import asyncio
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

from db import get_db
from models.zones import Zone, ZoneAlert
from models.issues import FieldIssue
from models.user import User
from pubsub import bus

router = APIRouter(prefix="/api/v1")

class AlertCreate(BaseModel):
    triggered_by_user_id: str
    message: Optional[str] = None

import os

DEMO_ZONES = [
    {
        "id": "z-1",
        "zone_code": "A12",
        "name": "Foundation Level 1 - North",
        "current_activity": "Rebar installation",
        "risk_score": 85,
        "active_worker_count": 14,
        "open_issue_count": 2,
        "last_scored_at": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "z-2",
        "zone_code": "B3",
        "name": "Podium Level 3 - East",
        "current_activity": "MEP rough-in",
        "risk_score": 45,
        "active_worker_count": 8,
        "open_issue_count": 2,
        "last_scored_at": datetime.utcnow().isoformat() + "Z"
    },
    {
        "id": "z-3",
        "zone_code": "C7",
        "name": "Tower Floor 12 - Core",
        "current_activity": "Concrete curing",
        "risk_score": 12,
        "active_worker_count": 22,
        "open_issue_count": 1,
        "last_scored_at": datetime.utcnow().isoformat() + "Z"
    }
]

def get_risk_level(score: int) -> str:
    if score >= 70: return "critical"
    elif score >= 40: return "elevated"
    else: return "normal"

@router.get("/projects/{project_id}/zones")
async def get_zones(project_id: str, db: AsyncSession = Depends(get_db)):
    is_demo = os.environ.get("DEMO_MODE", "false").lower() == "true"
    
    if is_demo:
        base_zones = DEMO_ZONES
    else:
        result = await db.execute(select(Zone).where(Zone.project_id == project_id))
        db_zones = result.scalars().all()
        base_zones = [
            {
                "id": z.id,
                "zone_code": z.zone_code,
                "name": z.name,
                "current_activity": z.current_activity,
                "risk_score": z.risk_score,
                "active_worker_count": z.active_worker_count,
                "open_issue_count": z.open_issue_count,
                "last_scored_at": z.last_scored_at.isoformat() if z.last_scored_at else None
            }
            for z in db_zones
        ]
        
    # Recompute risk levels and enrich
    enriched_zones = []
    for z in base_zones:
        z_copy = dict(z)
        z_copy["risk_level"] = get_risk_level(z_copy["risk_score"])
        if is_demo:
            z_copy["last_scored_at"] = datetime.utcnow().isoformat() + "Z"
        enriched_zones.append(z_copy)
        
    # Sort zones: Critical -> Elevated -> Normal, then by score descending
    risk_order = {"critical": 1, "elevated": 2, "normal": 3}
    enriched_zones.sort(key=lambda z: (risk_order.get(z["risk_level"], 3), -z["risk_score"]))

    critical_count = sum(1 for z in enriched_zones if z["risk_level"] == 'critical')
    total_workers = sum(z["active_worker_count"] for z in enriched_zones)
    total_issues = sum(z["open_issue_count"] for z in enriched_zones)
    
    return {
        "zones": enriched_zones,
        "summary": {
            "critical_count": critical_count,
            "total_workers": total_workers,
            "total_open_issues": total_issues,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }
    }

def _humanize_issue_type(issue_type: str | None) -> str:
    if not issue_type:
        return "Compliance Issue"
    return issue_type.replace("_", " ").title()


@router.get("/zones/{zone_id}/issues")
async def get_zone_issues(zone_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalars().first()

    if not zone:
        return {"zone_id": zone_id, "issues": []}

    # Real FieldIssue rows for this zone, matched by zone_code — the
    # compliance/vision agents write FieldIssue.zone_code (e.g. "A12"), not
    # the zones.id UUID this route is keyed by, so we resolve via the Zone
    # row first. Previously this returned 2 fixed-text templated issues
    # (ISS-001/ISS-002) regardless of what actually happened in the zone.
    issues_result = await db.execute(
        select(FieldIssue)
        .where(FieldIssue.zone_code == zone.zone_code, FieldIssue.status == "open")
        .order_by(FieldIssue.created_at.desc())
        .limit(50)
    )
    field_issues = issues_result.scalars().all()

    issues = [
        {
            "id": fi.id,
            "title": _humanize_issue_type(fi.issue_type),
            "description": fi.description,
            "severity": (fi.severity or "medium").upper(),
            "status": (fi.status or "open").upper(),
            "assigned_to": fi.escalated_to or fi.detected_by or "Unassigned",
            "created_at": fi.created_at.isoformat() if fi.created_at else datetime.utcnow().isoformat() + "Z",
            "due_date": None,
        }
        for fi in field_issues
    ]

    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "issues": issues
    }

@router.post("/zones/{zone_id}/alerts")
async def create_alert(zone_id: str, payload: AlertCreate, db: AsyncSession = Depends(get_db)):
    # Real recipient list: every active engineer/pm/admin user, not a fixed
    # ["super-1", "admin-1"] pair that doesn't correspond to any real User
    # row. Falls back to an empty list (not fabricated IDs) if none exist
    # yet in a fresh DB.
    recipients_result = await db.execute(
        select(User.id).where(User.role.in_(("engineer", "pm", "admin")), User.is_active == True)
    )
    notified_user_ids = [row[0] for row in recipients_result.all()]

    alert = ZoneAlert(
        zone_id=zone_id,
        triggered_by=payload.triggered_by_user_id,
        alert_type="manual",
        notified_user_ids=json.dumps(notified_user_ids)
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    return {
        "alert_id": alert.id,
        "notified_count": len(notified_user_ids),
        "timestamp": alert.created_at.isoformat() if alert.created_at else datetime.utcnow().isoformat() + "Z"
    }

@router.get("/projects/{project_id}/zones/stream")
async def stream_zones(request: Request, project_id: str):
    channel = f"zone_updates:{project_id}"
    q = bus.subscribe(channel)
    
    async def event_generator():
        try:
            while True:
                # If client disconnected, break
                if await request.is_disconnected():
                    break
                
                # Wait for next event
                message = await q.get()
                yield {
                    "data": json.dumps(message)
                }
        finally:
            bus.unsubscribe(channel, q)
            
    return EventSourceResponse(event_generator())
