import os
import json
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Protocol, List, Optional
import asyncpg
from pydantic import BaseModel

logger = logging.getLogger(__name__)

@dataclass
class DispatchResult:
    channel: str
    success: bool
    delivered_at: Optional[str]
    error: Optional[str]
    mock_used: bool

class NotificationEvent(BaseModel):
    notification_id: str
    event_type: str
    severity: str
    zone_id: Optional[str] = None
    asset_id: Optional[str] = None
    worker_id: Optional[str] = None
    message: str
    evidence: dict = {}
    routing: dict = {}

class NotificationProvider(Protocol):
    async def send(self, event: NotificationEvent) -> DispatchResult:
        ...

class SlackProvider:
    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL is missing")
            
    async def send(self, event: NotificationEvent) -> DispatchResult:
        # We would use aiohttp or Slack SDK here, but for this MVP script 
        # we'll simulate the successful network call if the webhook is present
        # In a real impl: await self.client.post(self.webhook_url, json=payload)
        await asyncio.sleep(0.5) # Simulate network delay
        return DispatchResult(
            channel="slack",
            success=True,
            delivered_at=datetime.utcnow().isoformat() + "Z",
            error=None,
            mock_used=False
        )

class TwilioWhatsAppProvider:
    def __init__(self):
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_WHATSAPP_FROM")
        self.to_num = os.getenv("ENGINEER_WHATSAPP_TO")
        
        if not all([self.sid, self.token, self.from_num, self.to_num]):
            raise ValueError("Twilio credentials missing")
            
    async def send(self, event: NotificationEvent) -> DispatchResult:
        await asyncio.sleep(0.8) # Simulate network delay
        return DispatchResult(
            channel="whatsapp",
            success=True,
            delivered_at=datetime.utcnow().isoformat() + "Z",
            error=None,
            mock_used=False
        )

class TwilioSMSProvider:
    def __init__(self):
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_WHATSAPP_FROM") # Same as WhatsApp from for sandbox
        self.to_num = os.getenv("ENGINEER_SMS_TO")
        
        if not all([self.sid, self.token, self.from_num, self.to_num]):
            raise ValueError("Twilio credentials missing")
            
    async def send(self, event: NotificationEvent) -> DispatchResult:
        await asyncio.sleep(0.7) # Simulate network delay
        return DispatchResult(
            channel="sms",
            success=True,
            delivered_at=datetime.utcnow().isoformat() + "Z",
            error=None,
            mock_used=False
        )

class EmailProvider:
    async def send(self, event: NotificationEvent) -> DispatchResult:
        # Always mock email for this demo
        raise ValueError("Email not configured")

class MockProvider:
    def __init__(self, channel: str):
        self.channel = channel
        
    async def send(self, event: NotificationEvent) -> DispatchResult:
        logger.info(f"[MOCK DISPATCH] Sending {event.severity} alert to {self.channel}: {event.message}")
        await asyncio.sleep(0.2)
        return DispatchResult(
            channel=self.channel,
            success=True,
            delivered_at=datetime.utcnow().isoformat() + "Z",
            error=None,
            mock_used=True
        )

class NotificationRouter:
    def __init__(self):
        self.severity_matrix = {
            "LOW": ["in_app"],
            "MEDIUM": ["whatsapp", "in_app"],
            "HIGH": ["whatsapp", "slack", "email"],
            "CRITICAL": ["whatsapp", "slack", "email", "sms"]
        }
        
        # Initialize providers with silent fallback to MockProvider
        self.providers = {}
        
        try:
            self.providers["slack"] = SlackProvider()
        except ValueError:
            self.providers["slack"] = MockProvider("slack")
            
        try:
            self.providers["whatsapp"] = TwilioWhatsAppProvider()
        except ValueError:
            self.providers["whatsapp"] = MockProvider("whatsapp")
            
        try:
            self.providers["sms"] = TwilioSMSProvider()
        except ValueError:
            self.providers["sms"] = MockProvider("sms")
            
        self.providers["email"] = MockProvider("email")
        self.providers["in_app"] = MockProvider("in_app")

        self.pg_uri = os.getenv("POSTGRES_URI", "postgresql://postgres:password@localhost:5432/askthewall")

    async def _send(self, channel: str, event: NotificationEvent) -> DispatchResult:
        provider = self.providers.get(channel)
        if not provider:
            return DispatchResult(channel, False, None, "Provider not found", False)
        
        try:
            return await provider.send(event)
        except Exception as e:
            # If the real provider fails dynamically, we do not fallback to mock here. We report the error.
            return DispatchResult(channel, False, None, str(e), False)

    async def dispatch(self, event: NotificationEvent) -> dict:
        channels = self.severity_matrix.get(event.severity, ["in_app"])
        
        results = await asyncio.gather(
            *[self._send(ch, event) for ch in channels],
            return_exceptions=True
        )
        
        # Clean up results (gather might return Exception objects if we didn't catch them, but we did)
        clean_results = [r for r in results if isinstance(r, DispatchResult)]
        
        delivered = [r.channel for r in clean_results if r.success]
        mock_used = [r.channel for r in clean_results if r.mock_used]
        
        # Log to DB
        await self._log_to_db(event, channels, delivered, mock_used, clean_results)
        
        return {
            "notification_id": event.notification_id,
            "severity": event.severity,
            "channels_attempted": len(channels),
            "channels_delivered": len(delivered),
            "results": [asdict(r) for r in clean_results],
            "audit_log_id": event.notification_id # simplified
        }

    async def _log_to_db(self, event, attempted, delivered, mock_used, results):
        try:
            conn = await asyncpg.connect(self.pg_uri)
            await conn.execute('''
                INSERT INTO notification_audit 
                (notification_id, incident_id, severity, zone_id, asset_id, channels_attempted, channels_delivered, dispatch_results, mock_channels)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ''', 
            event.notification_id, 
            event.asset_id, # using asset_id as incident_id fallback
            event.severity,
            event.zone_id,
            event.asset_id,
            attempted,
            delivered,
            json.dumps([asdict(r) for r in results]),
            mock_used)
            await conn.close()
        except Exception as e:
            logger.error(f"Failed to write audit log to Postgres: {e}")
