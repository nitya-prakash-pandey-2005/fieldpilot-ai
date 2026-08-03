from sqlalchemy import Column, DateTime, Float, Index, Integer, String
from sqlalchemy.sql import func
import uuid

from models.zones import Base


def generate_uuid():
    return str(uuid.uuid4())


class Beacon(Base):
    """A BLE beacon fixed to a known point on site.

    Survey data, not telemetry: someone physically mounts the beacon to a column
    and records where it is. Everything the localization agent does depends on
    these coordinates being right — a beacon logged at the wrong column silently
    assigns workers to the wrong zone, and therefore to the wrong blueprint.

    Coordinates are site-plan metres (same frame as the zone map), not lat/lon.
    Indoor positioning in a global frame buys nothing and loses precision.
    """
    __tablename__ = "beacons"

    id = Column(String, primary_key=True, default=generate_uuid)
    # The identifier the phone actually reports. For iBeacon this is
    # "uuid:major:minor"; for Eddystone the namespace:instance. Stored as an
    # opaque string so either scheme works without a schema change.
    beacon_id = Column(String(120), unique=True, nullable=False, index=True)
    label = Column(String(80), nullable=True)          # e.g. "Column C4 north face"

    project_id = Column(String, default="default-project", index=True)
    zone_code = Column(String(20), nullable=False, index=True)

    x = Column(Float, nullable=False)                  # site-plan metres
    y = Column(Float, nullable=False)
    floor = Column(Integer, default=0)

    # Calibrated RSSI at 1 m. Beacons vary by model and by battery level, so a
    # single global constant costs real accuracy — measure per beacon at install.
    tx_power = Column(Float, default=-59.0)
    # Per-beacon override for local obstruction (a beacon behind a steel column
    # decays faster than one in open air).
    path_loss_exponent = Column(Float, nullable=True)

    battery_pct = Column(Integer, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_beacons_project_zone", "project_id", "zone_code"),
    )


class WorkerPosition(Base):
    """Latest resolved position per worker, plus a trail for the site map.

    Append-only: each resolved scan writes a row, so the dashboard can draw
    where a worker has been during a shift and an incident can be tied to a
    location rather than just a zone label.
    """
    __tablename__ = "worker_positions"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, default="default-project", index=True)
    worker_id = Column(String(40), nullable=False, index=True)

    zone_code = Column(String(20), nullable=True, index=True)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    floor = Column(Integer, nullable=True)

    method = Column(String(24), nullable=True)         # multilateration | nearest_beacon | none
    confidence = Column(Float, nullable=True)
    accuracy_m = Column(Float, nullable=True)
    beacons_used = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("idx_worker_positions_worker_time", "worker_id", "created_at"),
    )
