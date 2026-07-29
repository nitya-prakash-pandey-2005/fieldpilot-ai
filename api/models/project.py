from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.sql import func
import uuid

# Import Base from zones to share the same declarative base
from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    project_type = Column(String, default="construction")  # construction | manufacturing | infrastructure
    start_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="active")  # active | completed | on_hold
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project")
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    asset_type = Column(String, nullable=False)  # e.g. "rebar", "conduit", "beam"
    status = Column(String, default="active")
    current_spec_version = Column(String, nullable=True)
    installed_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
