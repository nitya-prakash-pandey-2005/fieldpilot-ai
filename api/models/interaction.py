from sqlalchemy import Column, DateTime, Float, Index, String, Text
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class Interaction(Base):
    """
    One row per worker-initiated AI interaction: a scan, a voice query, a
    measurement, a drawing check.

    Two things depend on this existing:

    - The mobile app's History tab, which previously rendered a hardcoded
      three-item DEMO_HISTORY list because nothing server-side persisted what
      a worker had actually asked or scanned.
    - The audit trail in system_prompt.md §9.3 ("every agent action logged with
      timestamp"). Compliance verdicts were already persisted as FieldIssue
      rows, but only when they FAILED — a PASS, a voice question, or an
      inconclusive scan left no record at all, so there was no way to show what
      the system had been asked and answered over a shift.

    Deliberately append-only: nothing updates or deletes rows here. An audit
    log you can edit is not an audit log.
    """
    __tablename__ = "interactions"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project", index=True)
    worker_id = Column(String(40), index=True)
    zone_code = Column(String(10))

    # scan | voice | measurement | drawing_check | compliance
    kind = Column(String(20), nullable=False)
    # What the worker asked, or what was scanned.
    query = Column(Text, nullable=True)
    # What the system answered, in the worker's own terms.
    result = Column(Text, nullable=True)
    # PASS | FAIL | UNCERTAIN | INFO — nullable because a voice question has
    # no verdict, and coercing one would make the History feed lie.
    verdict = Column(String(16), nullable=True)
    severity = Column(String(16), nullable=True)
    confidence = Column(Float, nullable=True)

    # Which agent chain produced it, for the "10 agents" story on the dashboard.
    agent_chain = Column(String(120), nullable=True)
    latency_ms = Column(Float, nullable=True)
    # Optional pointer to evidence (annotated frame, report) — a path/URL, not
    # the blob itself; this table stays small enough to query cheaply.
    evidence_ref = Column(String(400), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_interactions_worker_time", "worker_id", "created_at"),
        Index("idx_interactions_project_time", "project_id", "created_at"),
    )
