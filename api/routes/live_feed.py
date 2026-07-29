"""
Live Feed Route — FieldPilot AI
---------------------------------
API endpoints for the real-time camera pipeline:

  POST /api/v1/live/frame          — ingest frame from live_camera_pipeline.py
  GET  /api/v1/live/hazard/{worker_id} — latest hazard assessment
  GET  /api/v1/live/status         — pipeline health + connected workers
"""

import time
import base64
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/live", tags=["Live Camera Pipeline"])

# ---------------------------------------------------------------------------
# In-memory state (per worker)
# ---------------------------------------------------------------------------

_latest_frames:     dict[str, str]  = {}    # worker_id → latest frame b64
_latest_detections: dict[str, dict] = {}    # worker_id → latest detection JSON
_latest_hazard:     dict[str, dict] = {}    # worker_id → latest hazard summary
_worker_last_seen:  dict[str, float]= {}    # worker_id → timestamp


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class LiveFramePayload(BaseModel):
    worker_id:  str
    zone_id:    str = "A12"
    frame:      str            # base64 JPEG
    detections: Optional[dict] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/frame")
async def ingest_live_frame(payload: LiveFramePayload):
    """
    Accept a frame + detections from the live_camera_pipeline.py script.
    Stores latest state and forwards to connected WebSocket listeners.
    """
    wid = payload.worker_id
    now = time.time()

    _latest_frames[wid]     = payload.frame
    _latest_detections[wid] = payload.detections or {}
    _worker_last_seen[wid]  = now

    # Build a lightweight hazard summary
    dets = payload.detections or {}
    zone = dets.get("zone_summary", {})
    comp = dets.get("compliance", [])

    ppe_ok  = all(c.get("ppe_score", 0) == 1.0 for c in comp)
    falls   = dets.get("fall_events", [])

    hazard = {
        "worker_id"    : wid,
        "zone_id"      : payload.zone_id,
        "timestamp"    : datetime.utcnow().isoformat() + "Z",
        "risk_level"   : zone.get("zone_risk_level", "normal"),
        "hazard_score" : zone.get("zone_risk_score", 0),
        "worker_count" : zone.get("worker_count", 0),
        "fall_events"  : falls,
        "ppe_violations": zone.get("ppe_violations", 0),
        "active_alerts": zone.get("active_alerts", []),
    }
    _latest_hazard[wid] = hazard

    # Broadcast to WebSocket listeners (dashboard)
    from api.main import broadcast_live_frame
    await broadcast_live_frame(wid, {
        "type"    : "live_frame",
        "frame"   : payload.frame,
        "hazard"  : hazard,
        "detections": {
            "compliance": comp,
            "fall_events": falls,
        },
    })

    return {"status": "ok", "worker_id": wid}


@router.get("/hazard/{worker_id}")
async def get_latest_hazard(worker_id: str):
    """Return the latest hazard assessment for a worker."""
    if worker_id not in _latest_hazard:
        return JSONResponse(
            status_code=404,
            content={"error": f"No live data for worker {worker_id}"}
        )
    return _latest_hazard[worker_id]


@router.get("/frame/{worker_id}")
async def get_latest_frame(worker_id: str):
    """Return the latest annotated frame (base64 JPEG) for a worker."""
    frame = _latest_frames.get(worker_id)
    if not frame:
        raise HTTPException(404, detail=f"No frame for worker {worker_id}")
    return {"worker_id": worker_id, "frame": frame}


@router.get("/status")
async def pipeline_status():
    """Return a summary of all currently active live workers."""
    now = time.time()
    workers = []
    for wid, last_seen in _worker_last_seen.items():
        age = now - last_seen
        workers.append({
            "worker_id" : wid,
            "last_seen" : round(age, 1),
            "active"    : age < 10.0,   # active if frame seen in last 10s
            "hazard"    : _latest_hazard.get(wid, {}),
        })
    return {
        "pipeline_active": len(workers) > 0,
        "active_workers" : sum(1 for w in workers if w["active"]),
        "workers"        : workers,
        "timestamp"      : datetime.utcnow().isoformat() + "Z",
    }
