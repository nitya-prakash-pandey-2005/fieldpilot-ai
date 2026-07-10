from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import sys
import os
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.notification.router import NotificationRouter, NotificationEvent

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
async def get_active_notifications():
    """
    Retrieves the latest 20 notifications from the audit log.
    """
    import asyncpg
    uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
    try:
        conn = await asyncpg.connect(uri)
        rows = await conn.fetch("SELECT * FROM notification_audit ORDER BY created_at DESC LIMIT 20")
        await conn.close()
        
        # Convert datetime to ISO string
        return {"status": "success", "data": [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]}
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
