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

@router.get("/zones/{zone_id}/issues")
async def get_zone_issues(zone_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalars().first()
    
    if not zone:
        return {"zone_id": zone_id, "issues": []}
        
    # Return mock issues for the dashboard demonstration
    issues = []
    if zone.open_issue_count > 0:
        issues.append({
            "id": "ISS-001",
            "title": "Rebar spacing violation",
            "description": "Spacing exceeds 102mm maximum.",
            "severity": "CRITICAL" if zone.risk_level == "critical" else "HIGH",
            "status": "OPEN",
            "assigned_to": "Jane Smith",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "due_date": None
        })
        if zone.open_issue_count > 1:
            issues.append({
                "id": "ISS-002",
                "title": "Missing PPE in sector 4",
                "description": "Worker spotted without hard hat.",
                "severity": "MEDIUM",
                "status": "OPEN",
                "assigned_to": "Safety Team",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "due_date": None
            })
            
    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "issues": issues
    }

@router.post("/zones/{zone_id}/alerts")
async def create_alert(zone_id: str, payload: AlertCreate, db: AsyncSession = Depends(get_db)):
    # Create the alert record
    alert = ZoneAlert(
        zone_id=zone_id,
        triggered_by=payload.triggered_by_user_id,
        alert_type="manual",
        notified_user_ids=json.dumps(["super-1", "admin-1"]) # Mock notification list
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    
    return {
        "alert_id": alert.id,
        "notified_count": 2,
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
