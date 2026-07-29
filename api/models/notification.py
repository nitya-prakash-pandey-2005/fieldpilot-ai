from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class NotificationAudit(Base):
    """
    Replaces the old raw-asyncpg `notification_audit` table in the separate
    `askthewall` DB. channels_* / dispatch_results are JSON stored as text
    (not Postgres ARRAY/JSON types) for the same sqlite-fallback-compat
    reason as models/observation.py.
    """
    __tablename__ = "notification_audit"

    id = Column(String, primary_key=True, default=generate_uuid)
    notification_id = Column(String, nullable=False)
    incident_id = Column(String, nullable=True)
    severity = Column(String, nullable=False)
    zone_id = Column(String, nullable=True)
    asset_id = Column(String, nullable=True)
    channels_attempted = Column(Text, nullable=True)   # JSON list string
    channels_delivered = Column(Text, nullable=True)   # JSON list string
    dispatch_results = Column(Text, nullable=True)      # JSON string
    mock_channels = Column(Text, nullable=True)         # JSON list string
    created_at = Column(DateTime(timezone=True), server_default=func.now())
