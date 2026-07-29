from sqlalchemy import Column, String, Float, DateTime, Text
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class ResolvedIncident(Base):
    """
    Agent 10 (Learning) — one row per resolved incident, the source data
    for the fine-tuning dataset export and executive dashboard metrics.
    Previously lived in a raw-asyncpg `resolved_incidents` table in a
    separate `askthewall` Postgres DB — that DB no longer exists (removed
    when the two-database split was unified), so this table now lives in
    the same `fieldpilot` DB/ORM as everything else.
    resolution/photos/outcome_metrics/tags are JSON stored as text (not
    Postgres JSONB/ARRAY) for the same sqlite-fallback-compat reason as
    models/observation.py and models/notification.py.
    """
    __tablename__ = "resolved_incidents"

    id = Column(String, primary_key=True, default=generate_uuid)
    incident_id = Column(String, unique=True, nullable=False)
    project_id = Column(String, nullable=False)
    zone_id = Column(String, nullable=False)
    asset_type = Column(String, nullable=False)
    issue_type = Column(String, nullable=False)
    measurement_at_detection = Column(Float, nullable=True)
    spec_value = Column(Float, nullable=True)
    resolution = Column(Text, nullable=False)        # JSON string
    photos = Column(Text, nullable=True)              # JSON string
    outcome_metrics = Column(Text, nullable=False)     # JSON string
    tags = Column(Text, nullable=True)                 # JSON string (list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
