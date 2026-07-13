from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Zone(Base):
    __tablename__ = "zones"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project")
    zone_code = Column(String, nullable=False) # e.g., "A12", "B3"
    name = Column(String, nullable=False) # e.g., "Foundation Level 1 - North"
    current_activity = Column(String) # e.g., "Rebar installation"
    risk_level = Column(String, default="normal") # 'critical', 'elevated', 'normal'
    risk_score = Column(Integer, default=0) # 0-100
    active_worker_count = Column(Integer, default=0)
    open_issue_count = Column(Integer, default=0)
    last_scored_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    alerts = relationship("ZoneAlert", back_populates="zone")

class ZoneAlert(Base):
    __tablename__ = "zone_alerts"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    zone_id = Column(String, ForeignKey("zones.id"))
    triggered_by = Column(String) # user_id
    alert_type = Column(String, default="manual")
    notified_user_ids = Column(String) # comma-separated list or JSON string for sqlite compat
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    zone = relationship("Zone", back_populates="alerts")
