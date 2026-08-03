"""
BLE indoor localization API — the zone-tracking layer.

Everything upstream of this hardcoded zone "A12". That was the single most
load-bearing fake value in the system: zone identity decides which blueprint an
observation is checked against, so a wrong zone means a correct measurement
compared to the wrong specification.

Flow:
    phone scans BLE advertisements (1 Hz)
      -> POST /localization/scan  { worker_id, beacons: [{beacon_id, rssi}] }
      -> registry lookup gives each beacon its surveyed x/y/zone
      -> RSSI smoothing, then multilateration (>=3 beacons) or nearest-beacon
      -> zone_code + position + honest confidence, persisted as a trail

The phone sends only what a radio can actually observe — an identifier and a
signal strength. It never sends a zone; deciding the zone is this service's job
and it is auditable here.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.localization.rssi import (
    DEFAULT_PATH_LOSS_EXPONENT,
    BeaconObservation,
    RssiSmoother,
    resolve_position,
)
from auth import CurrentUser, get_current_user_optional, require_role
from db import async_session
from models.beacon import Beacon, WorkerPosition

router = APIRouter(prefix="/api/v1/localization", tags=["BLE Localization"])

# One smoother per worker, kept in process. This is deliberately in-memory: it
# holds a few seconds of signal history, is worthless after a restart, and
# putting it in Redis would add a network round trip to a 1 Hz hot path for no
# benefit. Multi-instance deployments would pin a worker to an instance or
# accept a brief re-convergence.
_smoothers: dict[str, RssiSmoother] = {}
_MAX_SMOOTHERS = 500


def _smoother_for(worker_id: str) -> RssiSmoother:
    s = _smoothers.get(worker_id)
    if s is None:
        if len(_smoothers) >= _MAX_SMOOTHERS:
            _smoothers.clear()      # crude bound; these are cheap to rebuild
        s = RssiSmoother()
        _smoothers[worker_id] = s
    return s


# ---------------------------------------------------------------------------
# Scan resolution
# ---------------------------------------------------------------------------

class BeaconReading(BaseModel):
    beacon_id: str
    rssi: float = Field(..., le=0, ge=-127, description="dBm as reported by the radio")
    tx_power: Optional[float] = Field(None, description="if the advert carries it")


class ScanRequest(BaseModel):
    worker_id: str
    beacons: list[BeaconReading]
    project_id: str = "default-project"
    smooth: bool = Field(True, description="apply per-beacon temporal smoothing")
    persist: bool = Field(True, description="write the fix to the position trail")


@router.post("/scan")
async def resolve_scan(req: ScanRequest):
    if not req.beacons:
        return {
            "status": "no_beacons",
            "zone_code": None,
            "position": None,
            "message": "Scan contained no beacons. The worker is out of range of "
                       "the beacon network, or Bluetooth is off on the phone.",
        }

    ids = [b.beacon_id for b in req.beacons]
    registry: dict[str, Beacon] = {}
    try:
        async with async_session() as s:
            rows = (await s.execute(
                select(Beacon).where(Beacon.beacon_id.in_(ids))
            )).scalars().all()
            registry = {r.beacon_id: r for r in rows}
    except Exception as e:
        raise HTTPException(503, f"beacon registry unavailable: {e}")

    unknown = [i for i in ids if i not in registry]

    observations: list[BeaconObservation] = []
    exponents: list[float] = []
    for b in req.beacons:
        reg = registry.get(b.beacon_id)
        if reg is None:
            # An unsurveyed beacon carries no position, so it cannot contribute.
            # Reported back rather than dropped silently — an unknown beacon
            # usually means someone installed one without registering it.
            continue
        observations.append(BeaconObservation(
            beacon_id=b.beacon_id,
            rssi=b.rssi,
            tx_power=b.tx_power if b.tx_power is not None else reg.tx_power,
            x=reg.x, y=reg.y, floor=reg.floor, zone_code=reg.zone_code,
        ))
        if reg.path_loss_exponent:
            exponents.append(reg.path_loss_exponent)

    if not observations:
        return {
            "status": "no_known_beacons",
            "zone_code": None,
            "position": None,
            "unknown_beacons": unknown,
            "message": "None of the scanned beacons are in the registry. Register "
                       "them with POST /api/v1/localization/beacons including "
                       "their surveyed coordinates.",
        }

    if req.smooth:
        _smoother_for(req.worker_id).smooth_all(observations)

    n = sum(exponents) / len(exponents) if exponents else DEFAULT_PATH_LOSS_EXPONENT
    fix = resolve_position(observations, path_loss_exponent=n)

    if req.persist and fix.zone_code:
        try:
            async with async_session() as s:
                s.add(WorkerPosition(
                    project_id=req.project_id, worker_id=req.worker_id,
                    zone_code=fix.zone_code, x=fix.x, y=fix.y, floor=fix.floor,
                    method=fix.method, confidence=fix.confidence,
                    accuracy_m=fix.accuracy_m, beacons_used=fix.beacons_used,
                ))
                # Beacon liveness doubles as a battery/maintenance signal.
                now = datetime.now(timezone.utc)
                for o in observations:
                    reg = registry.get(o.beacon_id)
                    if reg is not None:
                        reg.last_seen_at = now
                await s.commit()
        except Exception as e:
            print(f"[LOCALIZATION] could not persist fix: {e}")

    return {
        "status": "ok",
        "worker_id": req.worker_id,
        "zone_code": fix.zone_code,
        "position": fix.as_dict(),
        "path_loss_exponent": n,
        "unknown_beacons": unknown,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class BeaconIn(BaseModel):
    beacon_id: str
    zone_code: str
    x: float
    y: float
    floor: int = 0
    label: Optional[str] = None
    tx_power: float = -59.0
    path_loss_exponent: Optional[float] = None
    project_id: str = "default-project"


@router.post("/beacons")
async def upsert_beacons(beacons: list[BeaconIn],
                         _user: CurrentUser = Depends(require_role("engineer", "pm", "admin"))):
    """Register or update surveyed beacons. Engineer+ only — these coordinates
    determine which specification every observation in the zone is judged
    against, so they are not worker-editable."""
    created = updated = 0
    try:
        async with async_session() as s:
            for b in beacons:
                existing = (await s.execute(
                    select(Beacon).where(Beacon.beacon_id == b.beacon_id)
                )).scalars().first()
                if existing is None:
                    s.add(Beacon(**b.model_dump()))
                    created += 1
                else:
                    for k, v in b.model_dump().items():
                        setattr(existing, k, v)
                    updated += 1
            await s.commit()
    except Exception as e:
        raise HTTPException(500, f"could not write beacons: {e}")
    return {"status": "ok", "created": created, "updated": updated}


@router.get("/beacons")
async def list_beacons(project_id: str = "default-project",
                       zone_code: Optional[str] = None):
    try:
        async with async_session() as s:
            stmt = select(Beacon).where(Beacon.project_id == project_id)
            if zone_code:
                stmt = stmt.where(Beacon.zone_code == zone_code)
            rows = (await s.execute(stmt.order_by(Beacon.zone_code))).scalars().all()
        now = datetime.now(timezone.utc)
        return {
            "status": "success",
            "count": len(rows),
            "data": [{
                "beacon_id": r.beacon_id, "label": r.label, "zone_code": r.zone_code,
                "x": r.x, "y": r.y, "floor": r.floor, "tx_power": r.tx_power,
                "path_loss_exponent": r.path_loss_exponent,
                "battery_pct": r.battery_pct,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
                # A beacon nobody has seen for an hour is probably dead or removed.
                "stale": bool(r.last_seen_at is None
                              or (now - (r.last_seen_at if r.last_seen_at.tzinfo
                                         else r.last_seen_at.replace(tzinfo=timezone.utc)))
                              > timedelta(hours=1)),
            } for r in rows],
        }
    except Exception as e:
        return {"status": "degraded", "count": 0, "data": [],
                "error": f"beacon registry unavailable: {e}"}


@router.delete("/beacons/{beacon_id}")
async def delete_beacon(beacon_id: str,
                        _user: CurrentUser = Depends(require_role("engineer", "pm", "admin"))):
    from sqlalchemy import delete as sa_delete
    async with async_session() as s:
        result = await s.execute(sa_delete(Beacon).where(Beacon.beacon_id == beacon_id))
        await s.commit()
    return {"status": "ok", "deleted": result.rowcount or 0}


# ---------------------------------------------------------------------------
# Worker position
# ---------------------------------------------------------------------------

@router.get("/worker/{worker_id}")
async def worker_position(worker_id: str, project_id: str = "default-project",
                          trail: int = Query(0, ge=0, le=500,
                                             description="also return the last N fixes")):
    try:
        async with async_session() as s:
            rows = (await s.execute(
                select(WorkerPosition)
                .where(WorkerPosition.worker_id == worker_id,
                       WorkerPosition.project_id == project_id)
                .order_by(WorkerPosition.created_at.desc())
                .limit(max(trail, 1))
            )).scalars().all()
    except Exception as e:
        return {"status": "degraded", "current": None, "error": str(e)}

    if not rows:
        return {"status": "unknown", "current": None, "trail": [],
                "message": f"No position has been resolved for {worker_id}. The "
                           f"phone has not posted a BLE scan yet."}

    def pack(r: WorkerPosition) -> dict:
        return {"zone_code": r.zone_code, "x": r.x, "y": r.y, "floor": r.floor,
                "method": r.method, "confidence": r.confidence,
                "accuracy_m": r.accuracy_m, "beacons_used": r.beacons_used,
                "at": r.created_at.isoformat() if r.created_at else None}

    return {"status": "ok", "worker_id": worker_id, "current": pack(rows[0]),
            "trail": [pack(r) for r in rows] if trail else []}


@router.get("/live")
async def live_positions(project_id: str = "default-project",
                         within_minutes: int = Query(10, ge=1, le=1440)):
    """Latest fix per worker — what the site map draws."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    try:
        async with async_session() as s:
            rows = (await s.execute(
                select(WorkerPosition)
                .where(WorkerPosition.project_id == project_id,
                       WorkerPosition.created_at >= cutoff)
                .order_by(WorkerPosition.created_at.desc())
            )).scalars().all()
    except Exception as e:
        return {"status": "degraded", "data": [], "error": str(e)}

    latest: dict[str, WorkerPosition] = {}
    for r in rows:
        latest.setdefault(r.worker_id, r)

    return {
        "status": "success",
        "window_minutes": within_minutes,
        "count": len(latest),
        "data": [{"worker_id": w, "zone_code": r.zone_code, "x": r.x, "y": r.y,
                  "floor": r.floor, "confidence": r.confidence,
                  "accuracy_m": r.accuracy_m, "method": r.method,
                  "at": r.created_at.isoformat() if r.created_at else None}
                 for w, r in latest.items()],
    }


@router.get("/status")
async def localization_status(project_id: str = "default-project"):
    """Is the beacon network actually usable?"""
    try:
        async with async_session() as s:
            beacons = (await s.execute(
                select(Beacon).where(Beacon.project_id == project_id))).scalars().all()
    except Exception as e:
        return {"available": False, "error": str(e)}

    by_zone: dict[str, int] = {}
    for b in beacons:
        by_zone[b.zone_code] = by_zone.get(b.zone_code, 0) + 1

    # Three beacons is the threshold for a solved 2D fix; below that a zone can
    # still be identified but no position can be computed.
    trilaterable = {z: n for z, n in by_zone.items() if n >= 3}

    return {
        "available": bool(beacons),
        "beacons_registered": len(beacons),
        "zones_covered": len(by_zone),
        "beacons_per_zone": by_zone,
        "zones_with_full_positioning": sorted(trilaterable),
        "zones_zone_only": sorted(z for z in by_zone if z not in trilaterable),
        "default_path_loss_exponent": DEFAULT_PATH_LOSS_EXPONENT,
        "note": "A zone needs >=3 registered beacons for multilateration. With 1-2 "
                "the worker's zone is still identified from the strongest beacon, "
                "but no x/y is computed.",
    }
