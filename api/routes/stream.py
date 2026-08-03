"""
Stream ingestion control plane.

The RTMP path the writeup describes, made real:

    phone / glasses / OBS  --RTMP publish-->  mediamtx :1935
                                                  |
    vision pipeline  <--RTSP pull--  mediamtx :8554
                                                  |
    browser preview  <--WebRTC/HLS--  mediamtx :8889 / :8888

A worker's phone publishes to rtmp://<host>:1935/live/<worker_id>. This service
starts an ingest worker that pulls the same stream over RTSP, duty-cycles frames,
runs the vision pipeline, and pushes results into the existing live-feed
WebSocket so the dashboard shows them exactly as it does for the webcam path.

Why pull over RTSP rather than RTMP: lower latency to consume, and mediamtx
re-serves one published stream to several consumers, so the pipeline and a
browser preview can watch the same feed at once.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from typing import Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.ingestion.stream_ingest import DEFAULT_ANALYSIS_INTERVAL_S, manager
from auth import CurrentUser, require_role

router = APIRouter(prefix="/api/v1/stream", tags=["Live Stream Ingestion (RTMP)"])

MEDIA_HOST = os.getenv("MEDIA_SERVER_HOST", "127.0.0.1")
RTMP_PORT = os.getenv("MEDIA_RTMP_PORT", "1935")
RTSP_PORT = os.getenv("MEDIA_RTSP_PORT", "8554")
HLS_PORT = os.getenv("MEDIA_HLS_PORT", "8888")
WEBRTC_PORT = os.getenv("MEDIA_WEBRTC_PORT", "8889")


def publish_url(worker_id: str) -> str:
    return f"rtmp://{MEDIA_HOST}:{RTMP_PORT}/live/{worker_id}"


def consume_url(worker_id: str) -> str:
    return f"rtsp://{MEDIA_HOST}:{RTSP_PORT}/live/{worker_id}"


class StartRequest(BaseModel):
    worker_id: str
    zone_id: str = "A12"
    # Omit to pull the worker's own published stream; supply to ingest any
    # RTSP/RTMP/HTTP source (an IP camera, a file, a test pattern).
    stream_url: Optional[str] = None
    analysis_interval_s: float = Field(DEFAULT_ANALYSIS_INTERVAL_S, ge=0.1, le=120.0)


@router.post("/start")
async def start_ingest(req: StartRequest,
                       _user: CurrentUser = Depends(require_role("engineer", "pm", "admin"))):
    """Begin consuming a worker's stream.

    Engineer+ only: this spawns a decode thread and runs models, so it is a
    resource commitment, not a read.
    """
    url = req.stream_url or consume_url(req.worker_id)

    # The ingest thread is synchronous and blocking, so results are handed back
    # to the event loop rather than touched from the thread directly.
    loop = asyncio.get_running_loop()

    def on_analysis(result: dict, frame, meta: dict) -> None:
        try:
            annotated = result.get("annotated_frame")
            b64 = None
            if annotated is not None:
                ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    b64 = base64.b64encode(buf).decode()

            payload = {
                "type": "stream_analysis",
                "worker_id": meta["worker_id"],
                "zone_id": meta["zone_id"],
                "source": "rtmp",
                "frame_index": meta["frame_index"],
                "zone_summary": result.get("zone_summary"),
                "compliance_checks": result.get("compliance_checks"),
                "fall_events": result.get("fall_events"),
                "struck_by_events": result.get("struck_by_events"),
                "frame": b64,
            }
            # call_soon_threadsafe, not run_coroutine_threadsafe().result():
            # blocking the ingest thread on the event loop would stall decoding
            # and reintroduce exactly the latency the duty cycle avoids.
            from main import broadcast_live_frame
            loop.call_soon_threadsafe(
                asyncio.create_task, broadcast_live_frame(meta["worker_id"], payload))
        except Exception as e:
            print(f"[STREAM] could not publish analysis: {e}")

    ing = manager.start(req.worker_id, url, req.zone_id,
                        req.analysis_interval_s, on_analysis)

    # Give the reader a moment to either connect or fail, so the response can
    # say which instead of always claiming success.
    await asyncio.sleep(1.5)

    return {
        "status": "started",
        "worker_id": req.worker_id,
        "consuming": url,
        "publish_to": publish_url(req.worker_id),
        "analysis_interval_s": req.analysis_interval_s,
        "connected": ing.stats.connected,
        "hint": None if ing.stats.connected else
                "Not connected yet. Nothing is publishing to this path — start a "
                "publisher (scripts/publish_test_stream.py, OBS, or the phone) "
                "and it will attach automatically; the ingestor retries with backoff.",
    }


@router.post("/stop/{worker_id}")
async def stop_ingest(worker_id: str,
                      _user: CurrentUser = Depends(require_role("engineer", "pm", "admin"))):
    stopped = manager.stop(worker_id)
    if not stopped:
        raise HTTPException(404, f"no ingestion running for {worker_id}")
    return {"status": "stopped", "worker_id": worker_id}


@router.post("/stop-all")
async def stop_all(_user: CurrentUser = Depends(require_role("engineer", "pm", "admin"))):
    return {"status": "stopped", "count": manager.stop_all()}


@router.get("/status")
async def stream_status():
    """Live ingestion state, including the achieved duty cycle.

    analysis_ratio is worth reading: if the configured interval is 5s on a 30fps
    stream it should sit near 1/150. A ratio far above that means frames are
    arriving slower than expected (a struggling uplink), and far below means
    analysis is falling behind.
    """
    st = manager.status()
    st["media_server"] = {
        "host": MEDIA_HOST,
        "rtmp_publish": f"rtmp://{MEDIA_HOST}:{RTMP_PORT}/live/<worker_id>",
        "rtsp_consume": f"rtsp://{MEDIA_HOST}:{RTSP_PORT}/live/<worker_id>",
        "hls_preview": f"http://{MEDIA_HOST}:{HLS_PORT}/live/<worker_id>/index.m3u8",
        "webrtc_preview": f"http://{MEDIA_HOST}:{WEBRTC_PORT}/live/<worker_id>",
        "reachable": _media_server_reachable(),
    }
    st["default_analysis_interval_s"] = DEFAULT_ANALYSIS_INTERVAL_S
    return st


def _media_server_reachable() -> bool:
    import socket
    try:
        with socket.create_connection((MEDIA_HOST, int(RTMP_PORT)), timeout=1.0):
            return True
    except Exception:
        return False


@router.get("/endpoints/{worker_id}")
async def endpoints_for(worker_id: str):
    """Everything a client needs to join the stream for this worker.

    The mobile app calls this rather than constructing URLs itself, so changing
    the media host is a server-side change.
    """
    return {
        "worker_id": worker_id,
        "publish": {
            "rtmp": publish_url(worker_id),
            "note": "The relay phone publishes here. On Android use the Camera2 "
                    "+ MediaCodec H.264 encoder into an RTMP muxer; from a "
                    "laptop, OBS with this as the custom server and "
                    f"'{worker_id}' as the stream key.",
        },
        "consume": {
            "rtsp": consume_url(worker_id),
            "hls": f"http://{MEDIA_HOST}:{HLS_PORT}/live/{worker_id}/index.m3u8",
            "webrtc": f"http://{MEDIA_HOST}:{WEBRTC_PORT}/live/{worker_id}",
        },
        "media_server_reachable": _media_server_reachable(),
    }
