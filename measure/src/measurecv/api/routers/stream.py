"""Live streaming: WebSocket measurement and MJPEG preview.

Two transports for two different consumers:

* **WebSocket** (``/v1/stream/ws``) -- the client pushes frames and receives
  JSON measurements. Suited to browsers and edge devices that hold the camera
  themselves.
* **MJPEG** (``/v1/stream/mjpeg``) -- the server pulls from a camera or RTSP
  URL and pushes annotated frames. Suited to dashboards and anything that can
  display an ``<img>``.

Both apply the same back-pressure rule: **drop, do not queue**. A client that
cannot keep up gets the newest frame, not a growing backlog of stale ones. For
live measurement, a fresh answer is worth more than a complete history, and
queueing turns a throughput problem into an unbounded-latency problem.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, StreamingResponse

from measurecv.api.deps import AppState, get_state, require_api_key
from measurecv.api.metrics import get_metrics
from measurecv.api.static import LIVE_PAGE
from measurecv.core.exceptions import MeasureCVError, VoiceError
from measurecv.core.logging import get_logger
from measurecv.core.types import Frame
from measurecv.pipeline.pipeline import MeasurementPipeline
from measurecv.pipeline.sources import decode_image_bytes, open_source
from measurecv.viz.annotate import AnnotationStyle, draw_scene
from measurecv.voice.tts import synthesize

log = get_logger(__name__)

router = APIRouter(prefix="/v1/stream", tags=["stream"])

#: Guard against a client streaming multi-megapixel frames at 60 fps.
_MAX_FRAME_BYTES = 12 * 1024 * 1024


@router.get("/live", response_class=HTMLResponse, summary="Browser live-view page")
async def live_page() -> HTMLResponse:
    """A camera client that runs in the browser.

    The same page serves a laptop webcam and a phone camera: frames are grabbed
    with ``getUserMedia``, sent over the WebSocket below, and measurements are
    drawn back over the page's own video element. Video therefore stays at
    camera framerate no matter how slow measurement is.

    ``getUserMedia`` requires a secure context. ``localhost`` qualifies, so a
    laptop works over plain HTTP; a phone reaching this over the LAN needs
    HTTPS or a tunnel, and the page says so rather than failing silently.

    Deliberately unauthenticated so it can be opened by scanning a URL --
    the WebSocket it connects to still enforces ``api.api_keys``.
    """
    return HTMLResponse(LIVE_PAGE)


@router.websocket("/ws")
async def websocket_stream(websocket: WebSocket) -> None:
    """Measure frames pushed over a WebSocket.

    Protocol
    --------
    Client sends binary frames (JPEG/PNG encoded). Server replies with one JSON
    message per processed frame::

        {"type": "measurement", "frame": 12, "objects": [...], ...}

    Text messages are treated as control commands: ``{"command": "reset"}``
    clears tracker and temporal state, ``{"command": "stats"}`` returns
    throughput counters, and ``{"command": "voice_query", "text": "..."}``
    returns synthesized speech audio for the given text.

    Each connection gets its **own pipeline view** for tracking state, because
    two clients streaming different cameras must not share track identities --
    that would fuse measurements of unrelated objects.
    """
    state: AppState | None = getattr(websocket.app.state, "app_state", None)
    if state is None:  # pragma: no cover
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    keys = state.config.api.api_keys
    if keys:
        supplied = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
        if supplied not in keys:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid API key")
            return

    await websocket.accept()

    # A dedicated pipeline shares the (expensive, thread-safe) models but keeps
    # per-connection tracker and smoother state.
    pipeline = MeasurementPipeline(state.config, models=state.pipeline.models)

    metrics = get_metrics()
    if metrics.enabled:
        metrics.active_streams.inc()

    frame_index = 0
    processed = 0
    dropped = 0
    started = time.time()
    busy = False

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            text = message.get("text")
            if text is not None:
                await _handle_command(websocket, pipeline, text, processed, dropped, started)
                continue

            data = message.get("bytes")
            if not data:
                continue
            if len(data) > _MAX_FRAME_BYTES:
                await websocket.send_json(
                    {"type": "error", "code": "frame_too_large", "message": "frame exceeds 12 MB"}
                )
                continue

            # Drop rather than queue: if a frame is still being measured, the
            # newly arrived one is discarded so latency stays bounded.
            if busy:
                dropped += 1
                continue

            busy = True
            try:
                image = decode_image_bytes(data)
                frame = Frame(
                    image=image, index=frame_index, timestamp=time.time(), source_id="websocket"
                )
                # Inference is blocking and CPU/GPU-bound; running it in a
                # thread keeps the event loop free to read the next frame and
                # to service other connections.
                scene = await asyncio.to_thread(pipeline.measure_frame, frame, track=True)
                metrics.record_scene(scene)

                payload = scene.to_dict()
                payload["type"] = "measurement"
                await websocket.send_json(payload)

                frame_index += 1
                processed += 1
            except MeasureCVError as exc:
                await websocket.send_json({"type": "error", **exc.to_dict()})
            except Exception as exc:
                log.exception("websocket_frame_failed", error=str(exc))
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "internal_error",
                        "message": "frame processing failed",
                    }
                )
            finally:
                busy = False

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - transport-level failures
        log.warning("websocket_closed_unexpectedly", error=str(exc))
    finally:
        if metrics.enabled:
            metrics.active_streams.dec()
        elapsed = time.time() - started
        log.info(
            "websocket_session_ended",
            processed=processed,
            dropped=dropped,
            duration_s=round(elapsed, 1),
            fps=round(processed / elapsed, 2) if elapsed > 0 else 0.0,
        )


async def _handle_command(
    websocket: WebSocket,
    pipeline: MeasurementPipeline,
    text_raw: str,
    processed: int,
    dropped: int,
    started: float,
) -> None:
    import json

    try:
        payload = json.loads(text_raw)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "control messages must be JSON"})
        return
    command = payload.get("command")

    if command == "reset":
        pipeline.reset_state()
        await websocket.send_json({"type": "ack", "command": "reset"})
    elif command == "stats":
        elapsed = max(1e-6, time.time() - started)
        await websocket.send_json(
            {
                "type": "stats",
                "processed": processed,
                "dropped": dropped,
                "fps": round(processed / elapsed, 2),
                "pipeline": pipeline.stats(),
            }
        )
    elif command == "voice_query":
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            await websocket.send_json(
                {"type": "error", "message": "voice_query requires a non-empty 'text' field"}
            )
            return
        if len(text) > 500:
            await websocket.send_json(
                {"type": "error", "message": "voice_query text must be 500 characters or fewer"}
            )
            return
        try:
            audio = await asyncio.to_thread(synthesize, text)
        except VoiceError as exc:
            await websocket.send_json({"type": "error", **exc.to_dict()})
            return
        await websocket.send_bytes(audio)
    else:
        await websocket.send_json({"type": "error", "message": f"unknown command: {command}"})


async def _mjpeg_frames(
    pipeline: MeasurementPipeline,
    source: str,
    quality: int,
    max_fps: float,
) -> AsyncIterator[bytes]:
    """Yield annotated frames as an MJPEG multipart stream."""
    frames = open_source(source)
    interval = 1.0 / max_fps if max_fps > 0 else 0.0
    last = 0.0

    try:
        iterator = iter(frames)
        while True:
            frame = await asyncio.to_thread(next, iterator, None)
            if frame is None:
                break

            now = time.monotonic()
            if interval and (now - last) < interval:
                continue
            last = now

            try:
                artifacts = await asyncio.to_thread(pipeline.measure_frame_full, frame, track=True)
                annotated = draw_scene(
                    artifacts.image,
                    artifacts.scene,
                    masks=[m.mask for m in artifacts.masks],
                    intrinsics=artifacts.intrinsics,
                    style=AnnotationStyle(show_volume=True),
                )
                get_metrics().record_scene(artifacts.scene)
            except MeasureCVError as exc:
                log.warning("mjpeg_frame_failed", error=str(exc))
                annotated = frame.image

            ok, buffer = cv2.imencode(
                ".jpg",
                cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR),
                [int(cv2.IMWRITE_JPEG_QUALITY), quality],
            )
            if not ok:
                continue

            payload = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n"
            )
    finally:
        frames.close()
        log.info("mjpeg_stream_ended", source=source)


@router.get(
    "/mjpeg",
    summary="Annotated MJPEG preview from a server-side source",
    dependencies=[Depends(require_api_key)],
)
async def mjpeg_stream(
    state: Annotated[AppState, Depends(get_state)],
    source: Annotated[str, Query(description="Camera index, file path, or rtsp:// URL")] = "0",
    quality: Annotated[int, Query(ge=30, le=100)] = 80,
    max_fps: Annotated[float, Query(gt=0, le=60)] = 10.0,
) -> StreamingResponse:
    """Stream annotated frames from a camera or network stream.

    The source is opened **server-side**, so this endpoint is only appropriate
    on a trusted network: it can be pointed at any URL the server can reach.
    Restrict it with ``api.api_keys`` before exposing it.
    """
    if not state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="models are still loading"
        )

    pipeline = MeasurementPipeline(state.config, models=state.pipeline.models)
    return StreamingResponse(
        _mjpeg_frames(pipeline, source, quality, max_fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/snapshot",
    summary="Single annotated frame from a source",
    dependencies=[Depends(require_api_key)],
)
async def snapshot(
    state: Annotated[AppState, Depends(get_state)],
    source: Annotated[str, Query()] = "0",
) -> dict[str, Any]:
    """Grab and measure one frame -- useful for testing a camera URL."""
    frames = open_source(source)
    try:
        frame = await asyncio.to_thread(next, iter(frames), None)
        if frame is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"no frame available from {source}"
            )
        scene = await asyncio.to_thread(state.pipeline.measure_frame, frame, track=False)
        return scene.to_dict()
    finally:
        frames.close()


def _encode_jpeg(image: np.ndarray, quality: int = 85) -> bytes:  # pragma: no cover - helper
    ok, buffer = cv2.imencode(
        ".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    )
    return buffer.tobytes() if ok else b""
