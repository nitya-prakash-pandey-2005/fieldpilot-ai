from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class ComplianceEvent(Base):
    """
    Replaces the old raw-asyncpg `compliance_events` table that lived in a
    separate `askthewall` Postgres DB. Same data, now in the same DB/ORM as
    Zone/FieldIssue so a FAIL can actually be linked to the FieldIssue it
    creates instead of the two living in disconnected data stores.
    """
    __tablename__ = "compliance_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    # ValidationRequest.zone_id (agents/compliance/validator.py) is actually
    # a human zone code like "A12", not the zones.id UUID primary key —
    # stored as a plain string here, same convention FieldIssue already
    # uses for its zone_code column, rather than a strict FK that would
    # reject every real caller.
    zone_code = Column(String, nullable=True)
    asset_id = Column(String, nullable=True)
    field_issue_id = Column(String, ForeignKey("field_issues.id"), nullable=True)
    severity = Column(String, nullable=False)
    measured_value = Column(Float, nullable=True)
    spec_value = Column(Float, nullable=True)
    deviation_pct = Column(Float, nullable=True)
    # Measurement confidence from ComplianceEngine.validate() (Agent 5 already
    # computes this — it just never made it past the response payload into
    # persisted storage, so the dashboard had no way to show "the model's
    # own certainty" per system_prompt.md's confidence-indicator spec).
    confidence = Column(Float, nullable=True)
    worker_id = Column(String, nullable=True)
    status = Column(String, default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
