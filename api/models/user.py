from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


# system_prompt.md Section 9.1's role set — Worker sees their own scan/
# issue/voice flow, Engineer+ can resolve/escalate/reject, PM+ sees
# cross-zone risk, Admin/Executive get full access including the raw
# Cypher graph console.
ROLES = ("worker", "engineer", "pm", "admin", "executive")


class User(Base):
    """
    First real identity model in the codebase — previously there was no
    auth anywhere (verified by repo-wide grep this session): no JWT, no
    login route, no RBAC, and notably no auth guard at all on
    POST /api/v1/graph/query, which accepts arbitrary Cypher.
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="worker")  # one of ROLES
    zone_code = Column(String, nullable=True)  # worker's assigned zone, if any
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
