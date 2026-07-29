from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class Observation(Base):
    """
    Generic per-frame event log from the perception agents (Vision,
    Measurement, Pose). Mirrors the :Observation node in system_prompt.md's
    Neo4j schema, translated into a SQL table for the unified Postgres DB.
    raw_data / processed_result are JSON stored as text (not the Postgres
    JSON column type) to stay compatible with the sqlite fallback used by
    scripts/nightly_flywheel_training.py, matching the existing
    notified_user_ids convention in models/zones.py.
    """
    __tablename__ = "observations"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project")
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    zone_code = Column(String, nullable=True)  # human zone code (e.g. "A12") when the real zones.id isn't known
    asset_id = Column(String, ForeignKey("assets.id"), nullable=True)
    worker_id = Column(String, nullable=True)
    track_id = Column(Integer, nullable=True)
    agent_source = Column(String, default="vision_agent")  # vision_agent | measurement_agent | pose_estimator
    observation_type = Column(String, nullable=False)  # hazard_assessment | measurement | ppe_check
    raw_data = Column(Text, nullable=True)         # JSON string
    processed_result = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime(timezone=True), server_default=func.now())
