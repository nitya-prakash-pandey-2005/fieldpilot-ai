from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import sys
import os
import uuid
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.notification.router import NotificationRouter, NotificationEvent
from db import get_db
from models.notification import NotificationAudit
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/notification", tags=["Notification Agent (Agent 9)"])

# Initialize Router
notification_router = NotificationRouter()

@router.post("/dispatch")
async def dispatch_notification(event: NotificationEvent):
    """
    Intelligently routes alerts based on severity matrix across Slack, Twilio, and Email.
    """
    try:
        result = await notification_router.dispatch(event)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/active")
async def get_active_notifications(db: AsyncSession = Depends(get_db)):
    """
    Retrieves the latest 20 notifications from the audit log.
    """
    try:
        result = await db.execute(
            select(NotificationAudit).order_by(NotificationAudit.created_at.desc()).limit(20)
        )
        rows = result.scalars().all()
        return {
            "status": "success",
            "data": [
                {
                    "id": r.id,
                    "notification_id": r.notification_id,
                    "incident_id": r.incident_id,
                    "severity": r.severity,
                    "zone_id": r.zone_id,
                    "asset_id": r.asset_id,
                    "channels_attempted": json.loads(r.channels_attempted) if r.channels_attempted else [],
                    "channels_delivered": json.loads(r.channels_delivered) if r.channels_delivered else [],
                    "dispatch_results": json.loads(r.dispatch_results) if r.dispatch_results else [],
                    "mock_channels": json.loads(r.mock_channels) if r.mock_channels else [],
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/test-fire")
async def test_fire_notification():
    """
    Fires a hardcoded CRITICAL alert to verify all channels before a demo.
    Guarded by DEV_MODE.
    """
    if os.getenv("DEV_MODE", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Test fire is only available in DEV_MODE")
        
    test_event = NotificationEvent(
        notification_id=str(uuid.uuid4()),
        event_type="SYSTEM_TEST",
        severity="CRITICAL",
        zone_id="DEMO-ZONE",
        asset_id="DEMO-ASSET",
        worker_id="SYS-ADMIN",
        message="🔴 TEST FIRE: This is a system connectivity test from Agent 9. Please ignore.",
        evidence={"note": "Pre-demo connectivity check"},
        routing={"engineer_id": "ALL"}
    )
    
    try:
        result = await notification_router.dispatch(test_event)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
