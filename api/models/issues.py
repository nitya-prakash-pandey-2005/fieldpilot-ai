from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

# Import Base from zones to share the same declarative base
from models.zones import Base

def generate_uuid():
    return str(uuid.uuid4())

class FieldIssue(Base):
    __tablename__ = "field_issues"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project")
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    zone_code = Column(String(10))
    issue_type = Column(String)
    severity = Column(String, default="medium") # 'critical', 'high', 'medium', 'low'
    status = Column(String, default="open") # 'open', 'resolved', 'escalated', 'dismissed'
    description = Column(String, nullable=False)
    
    # Measurement fields
    deviation_pct = Column(Numeric(5, 2), nullable=True)
    measured_value = Column(String, nullable=True)
    expected_value = Column(String, nullable=True)
    worker_id = Column(String(20), nullable=True)
    
    # Resolution fields
    resolved_by = Column(String, nullable=True) # Assuming user IDs are strings (UUIDs)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_note = Column(String, nullable=True)
    escalated_to = Column(String, nullable=True)
    escalated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Detection metadata
    detected_by = Column(String, default="vision_agent")
    drawing_ref = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Indexes
    __table_args__ = (
        Index("idx_field_issues_project_status", "project_id", "status", "severity"),
    )
