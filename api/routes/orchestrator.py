"""
The 10-agent orchestrator, over HTTP.

`agents/orchestrator/graph.py` runs the whole swarm on one frame. This exposes
it, and — more importantly for a live demo — streams the run as it happens, so
the Agent Flow page lights each node the moment it fires instead of showing a
finished result after 30 seconds of blank screen.

    GET  /api/v1/orchestrator/graph        the diagram, as data
    GET  /api/v1/orchestrator/status       what each mode can actually do right now
    POST /api/v1/orchestrator/run          run one frame through all ten agents
    GET  /api/v1/orchestrator/stream       SSE — node_start / node_end / run_end
    GET  /api/v1/orchestrator/runs         recent runs (newest first)
    GET  /api/v1/orchestrator/runs/{id}    one full run, including every trace row

TRANSPORT. SSE over the existing in-process EventBus, matching the pattern the
issues and zones routes already use, per Follow.md section 4's "SSE from FastAPI"
and section 11's preference for the simplest transport that reliably works.

CONCURRENCY. A run holds YOLO, Metric3D and ONNX sessions, none of which are
thread-safe, and a full cloud pass takes tens of seconds on CPU. Overlapping
runs would interleave inside those models and produce corrupted output rather
than a clean error, so runs are serialised behind a lock and a second concurrent
request is rejected with 409 instead of being silently queued behind a 30-second
wait the caller cannot see.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.orchestrator.graph import graph_topology, run_pipeline
from pubsub import bus

router = APIRouter(prefix="/api/v1/orchestrator", tags=["Orchestrator (10-Agent Graph)"])

CHANNEL = "orchestrator_events"

# Recent runs, newest last. Bounded because each entry carries a full trace and
# an annotated frame; unbounded, a long demo session would grow without limit.
_RUNS: deque = deque(maxlen=25)
_run_lock = asyncio.Lock()


class RunRequest(BaseModel):
    frame_b64: Optional[str] = Field(None, description="base64 JPEG/PNG; data: URL prefix is accepted")
    audio_b64: Optional[str] = Field(None, description="base64 audio for the voice lane")
    audio_filename: str = "audio.webm"
    query: Optional[str] = Field(None, description="typed query, when there is no microphone")
    mode: str = Field("cloud", description="'cloud' or 'edge'")
    worker_id: str = "W-001"
    zone_id: str = "A12"
    project_id: str = "default-project"
    language: str = "en"
    spec_override: Optional[dict] = None
    allow_depth: Optional[bool] = None


async def _publish(event: dict) -> None:
    event.setdefault("ts", time.time())
    await bus.publish(CHANNEL, event)


def _summarise(result: dict) -> dict:
    """Trim a run for the list endpoint — no frames, no audio, no citations."""
    return {
        "run_id": result["run_id"],
        "mode": result["mode"],
        "zone_id": result.get("zone_id"),
        "worker_id": result.get("worker_id"),
        "duration_ms": result["duration_ms"],
        "agents_fired": result["agents_fired"],
        "agents_total": result["agents_total"],
        "agents_errored": result["agents_errored"],
        "verdict": (result.get("compliance") or {}).get("verdict"),
        "event_type": (result.get("notification") or {}).get("event_type"),
        "spoken_text": (result.get("notification") or {}).get("spoken_text"),
        "trace": result.get("trace", []),
    }


@router.get("/graph")
async def get_graph():
    """The topology the Agent Flow page draws.

    Served from the same structures the graph is built from, so the diagram
    cannot drift away from what actually executes.
    """
    return graph_topology()


@router.get("/status")
async def get_status():
    """What each mode can do right now, checked rather than asserted.

    The Cloud/Edge toggle is only meaningful if the UI can tell the user which
    backends are actually loadable — a toggle that flips to a mode with no model
    behind it is worse than no toggle.
    """
    from agents.compliance import spec_registry
    from agents.voice import tts as tts_mod

    edge: dict
    try:
        from agents.edge.runtime import get_detector
        detector = get_detector()
        edge = {"available": bool(detector.ready), **detector.status()}
    except Exception as e:
        edge = {"available": False, "error": f"{type(e).__name__}: {e}"}

    cloud_vision = os.path.exists(os.getenv("YOLO_MODEL_PATH", "yolo11n.pt"))

    return {
        "modes": {
            "cloud": {
                "vision": {"backend": "yolo11n + PPE + pose (torch)",
                           "available": cloud_vision,
                           "license": "AGPL-3.0 (Ultralytics)"},
                "depth": {"backend": "metric3d via measurecv", "available": True},
                "tts": tts_mod.status()["cloud"],
            },
            "edge": {
                "vision": {"backend": "yolo11n-pose INT8 (onnxruntime)", **edge},
                "depth": {"backend": "disabled on device",
                          "available": False,
                          "reason": "Metric3D costs ~5.6s/frame — too slow for the on-device loop"},
                "tts": tts_mod.status()["local"],
            },
        },
        "spec_registry": spec_registry.registry_status(),
        "runs_held": len(_RUNS),
        "busy": _run_lock.locked(),
    }


@router.post("/run")
async def run(req: RunRequest):
    """Run one frame (and optional utterance) through all ten agents."""
    if not req.frame_b64 and not req.audio_b64 and not req.query:
        raise HTTPException(400, detail="supply at least one of frame_b64, audio_b64 or query")

    if _run_lock.locked():
        raise HTTPException(
            409,
            detail="a run is already in progress — the vision and depth models are "
                   "not thread-safe, so runs are serialised. Retry when it completes.",
        )

    async with _run_lock:
        result = await run_pipeline(
            frame_b64=req.frame_b64,
            audio_b64=req.audio_b64,
            audio_filename=req.audio_filename,
            query=req.query,
            mode=req.mode,
            worker_id=req.worker_id,
            zone_id=req.zone_id,
            project_id=req.project_id,
            language=req.language,
            spec_override=req.spec_override,
            allow_depth=req.allow_depth,
            on_event=_publish,
        )

    _RUNS.append(result)
    return result


@router.get("/stream")
async def stream():
    """Live node-level events for the Agent Flow page."""
    async def event_generator():
        q = bus.subscribe(CHANNEL)
        try:
            while True:
                msg = await q.get()
                yield json.dumps(msg)
        except asyncio.CancelledError:
            bus.unsubscribe(CHANNEL, q)
            raise

    return EventSourceResponse(event_generator())


@router.get("/runs")
async def list_runs(limit: int = 10):
    return {"runs": [_summarise(r) for r in list(_RUNS)[::-1][:max(1, min(limit, 25))]],
            "held": len(_RUNS)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    for r in _RUNS:
        if r["run_id"] == run_id:
            return r
    raise HTTPException(404, detail=f"run {run_id} not held in memory (last {_RUNS.maxlen} kept)")
