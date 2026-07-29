import os
import sys
import json
import logging
import asyncio
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Protocol, List, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Make the api/ package (models.*, db.py) importable — same convention as
# agents/compliance/validator.py.
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
if _API_DIR not in sys.path:
    sys.path.append(_API_DIR)

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
    """
    Real Slack Incoming Webhook POST. Previously this only checked that
    SLACK_WEBHOOK_URL was set and then slept + returned success without
    ever making a network call — "configured" and "actually delivering"
    were not the same thing. No webhook is configured yet, so in practice
    this still falls back to MockProvider (see NotificationRouter.__init__)
    until a real SLACK_WEBHOOK_URL is added to .env — zero code changes
    needed at that point.
    """
    def __init__(self):
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL is missing")

    async def send(self, event: NotificationEvent) -> DispatchResult:
        import httpx
        severity_emoji = {"LOW": "\U0001F7E2", "MEDIUM": "\U0001F7E1", "HIGH": "\U0001F7E0", "CRITICAL": "\U0001F534"}
        payload = {
            "text": f"{severity_emoji.get(event.severity, '')} *{event.severity} — {event.event_type}*\n"
                    f"Zone: {event.zone_id or 'n/a'} | Asset: {event.asset_id or 'n/a'}\n"
                    f"{event.message}"
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            return DispatchResult(
                channel="slack", success=True,
                delivered_at=datetime.utcnow().isoformat() + "Z",
                error=None, mock_used=False,
            )
        except Exception as e:
            return DispatchResult(channel="slack", success=False, delivered_at=None, error=str(e), mock_used=False)


class TwilioWhatsAppProvider:
    """
    Real Twilio WhatsApp send via the official SDK. Same "configured but
    not delivering" gap as SlackProvider previously had — the twilio SDK
    call is synchronous, so it's run in a thread via asyncio.to_thread to
    avoid blocking the event loop.
    """
    def __init__(self):
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_WHATSAPP_FROM")
        self.to_num = os.getenv("ENGINEER_WHATSAPP_TO")

        if not all([self.sid, self.token, self.from_num, self.to_num]):
            raise ValueError("Twilio credentials missing")

    async def send(self, event: NotificationEvent) -> DispatchResult:
        try:
            from twilio.rest import Client

            def _send():
                client = Client(self.sid, self.token)
                return client.messages.create(
                    from_=f"whatsapp:{self.from_num}",
                    to=f"whatsapp:{self.to_num}",
                    body=f"[{event.severity}] {event.event_type}: {event.message}",
                )

            msg = await asyncio.to_thread(_send)
            success = msg.status not in ("failed", "undelivered")
            return DispatchResult(
                channel="whatsapp", success=success,
                delivered_at=datetime.utcnow().isoformat() + "Z" if success else None,
                error=msg.error_message if not success else None, mock_used=False,
            )
        except Exception as e:
            return DispatchResult(channel="whatsapp", success=False, delivered_at=None, error=str(e), mock_used=False)


class TwilioSMSProvider:
    def __init__(self):
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_WHATSAPP_FROM") # Same as WhatsApp from for sandbox
        self.to_num = os.getenv("ENGINEER_SMS_TO")

        if not all([self.sid, self.token, self.from_num, self.to_num]):
            raise ValueError("Twilio credentials missing")

    async def send(self, event: NotificationEvent) -> DispatchResult:
        try:
            from twilio.rest import Client

            def _send():
                client = Client(self.sid, self.token)
                return client.messages.create(
                    from_=self.from_num,
                    to=self.to_num,
                    body=f"[{event.severity}] {event.event_type}: {event.message}",
                )

            msg = await asyncio.to_thread(_send)
            success = msg.status not in ("failed", "undelivered")
            return DispatchResult(
                channel="sms", success=success,
                delivered_at=datetime.utcnow().isoformat() + "Z" if success else None,
                error=msg.error_message if not success else None, mock_used=False,
            )
        except Exception as e:
            return DispatchResult(channel="sms", success=False, delivered_at=None, error=str(e), mock_used=False)

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
        """
        Write the audit log via the same unified Postgres DB/ORM as
        FieldIssue/ComplianceEvent — previously this wrote to a raw-asyncpg
        `notification_audit` table in a separate `askthewall` database that
        nothing else in the app could join against.
        """
        try:
            from db import async_session
            from models.notification import NotificationAudit

            async with async_session() as session:
                session.add(NotificationAudit(
                    notification_id=event.notification_id,
                    incident_id=event.asset_id,  # using asset_id as incident_id fallback, matching prior behavior
                    severity=event.severity,
                    zone_id=event.zone_id,
                    asset_id=event.asset_id,
                    channels_attempted=json.dumps(attempted),
                    channels_delivered=json.dumps(delivered),
                    dispatch_results=json.dumps([asdict(r) for r in results]),
                    mock_channels=json.dumps(mock_used),
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to write audit log to Postgres: {e}")
