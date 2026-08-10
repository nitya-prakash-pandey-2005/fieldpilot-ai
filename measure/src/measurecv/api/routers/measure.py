"""Measurement endpoints."""

from __future__ import annotations

import base64
import json
import time
from typing import Annotated, Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from measurecv.api.deps import AppState, enforce_upload_limit, get_state, require_api_key
from measurecv.api.metrics import get_metrics
from measurecv.api.schemas import MeasureOptions, SceneResponse
from measurecv.calibration.intrinsics import CameraIntrinsics, IntrinsicsSource
from measurecv.core.logging import get_logger
from measurecv.core.types import Frame, SceneMeasurement
from measurecv.export.serializers import encode_rle
from measurecv.measurement.engine import scene_analytics
from measurecv.pipeline.sources import decode_image_bytes
from measurecv.viz.annotate import AnnotationStyle, draw_depth_map, draw_scene

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["measure"], dependencies=[Depends(require_api_key)])

#: Cap on batch size. Each image holds several hundred MB of intermediates
#: while in flight, so an unbounded batch is an easy out-of-memory vector.
_MAX_BATCH = 16


def _parse_options(raw: str | None) -> MeasureOptions:
    if not raw:
        return MeasureOptions()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'options' must be valid JSON: {exc}",
        ) from exc
    try:
        return MeasureOptions.model_validate(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _intrinsics_from_options(options: MeasureOptions) -> CameraIntrinsics | None:
    if options.intrinsics is None:
        return None
    model = options.intrinsics
    return CameraIntrinsics(
        fx=model.fx,
        fy=model.fy,
        cx=model.cx,
        cy=model.cy,
        width=model.width,
        height=model.height,
        distortion=np.asarray(model.distortion or [0, 0, 0, 0, 0], dtype=np.float64),
        source=IntrinsicsSource.PROVIDED,
        focal_uncertainty=model.focal_uncertainty,
    )


def _png_base64(image: np.ndarray) -> str:
    """Encode RGB as a base64 PNG. PNG, not JPEG: these are diagnostic images
    and JPEG artefacts around mask edges defeat the purpose.
    """
    ok, buffer = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:  # pragma: no cover - encoder failure is not reachable in practice
        raise HTTPException(status_code=500, detail="failed to encode image")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _apply_overrides(state: AppState, options: MeasureOptions) -> dict[str, Any]:
    """Temporarily override config for one request.

    Returns the previous values so the caller can restore them. Mutating shared
    configuration is only safe because measurement requests are serialised by
    the model manager's inference slot; the restore happens in a ``finally``.
    """
    config = state.config
    previous: dict[str, Any] = {}

    if options.score_threshold is not None:
        previous["score_threshold"] = config.detection.score_threshold
        config.detection.score_threshold = options.score_threshold
    if options.classes is not None:
        previous["class_whitelist"] = config.detection.class_whitelist
        config.detection.class_whitelist = options.classes
    if options.min_confidence is not None:
        previous["min_confidence"] = config.measurement.min_confidence
        config.measurement.min_confidence = options.min_confidence
    if options.volume_method is not None:
        previous["volume_method"] = config.measurement.volume_method
        config.measurement.volume_method = options.volume_method
    if options.dimension_method is not None:
        previous["dimension_method"] = config.measurement.dimension_method
        config.measurement.dimension_method = options.dimension_method
    return previous


def _restore_overrides(state: AppState, previous: dict[str, Any]) -> None:
    config = state.config
    if "score_threshold" in previous:
        config.detection.score_threshold = previous["score_threshold"]
    if "class_whitelist" in previous:
        config.detection.class_whitelist = previous["class_whitelist"]
    if "min_confidence" in previous:
        config.measurement.min_confidence = previous["min_confidence"]
    if "volume_method" in previous:
        config.measurement.volume_method = previous["volume_method"]
    if "dimension_method" in previous:
        config.measurement.dimension_method = previous["dimension_method"]


def _build_response(
    scene: SceneMeasurement,
    request_id: str | None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = scene.to_dict()
    payload["request_id"] = request_id
    if extras:
        payload.update(extras)
    return payload


@router.post(
    "/measure",
    response_model=SceneResponse,
    summary="Measure objects in a single image",
    response_description="Per-object dimensions, volume, distance and uncertainties",
)
async def measure_image(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
    file: Annotated[UploadFile, File(description="Image file (JPEG, PNG, WebP, BMP, TIFF)")],
    options: Annotated[str | None, Form(description="JSON-encoded MeasureOptions")] = None,
) -> dict[str, Any]:
    """Detect, segment, and measure every object in an uploaded image.

    Returns metric dimensions with 1-sigma uncertainties. Read the
    ``calibration_source`` field: ``assumed_fov`` means no calibration was
    available and the absolute scale carries roughly 15% uncertainty.
    """
    started = time.perf_counter()
    parsed = _parse_options(options)

    data = await file.read()
    enforce_upload_limit(state, len(data), file.filename or "upload")
    image = decode_image_bytes(data)

    override = _intrinsics_from_options(parsed)
    if override is not None and (override.width, override.height) != (
        image.shape[1],
        image.shape[0],
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"supplied intrinsics are for {override.width}x{override.height} but the image is "
                f"{image.shape[1]}x{image.shape[0]}; intrinsics are resolution-dependent"
            ),
        )

    previous = _apply_overrides(state, parsed)
    try:
        frame = Frame(
            image=image, index=0, timestamp=time.time(), source_id=file.filename or "upload"
        )
        artifacts = state.pipeline.measure_frame_full(
            frame, intrinsics=override, exif=None, track=False
        )
    finally:
        _restore_overrides(state, previous)

    scene = artifacts.scene
    extras: dict[str, Any] = {}

    if parsed.include_masks:
        extras["masks"] = [encode_rle(m.mask) for m in artifacts.masks]
    if parsed.include_annotated_image:
        annotated = draw_scene(
            artifacts.image,
            scene,
            masks=[m.mask for m in artifacts.masks],
            intrinsics=artifacts.intrinsics,
            style=AnnotationStyle(),
        )
        extras["annotated_image_png_b64"] = _png_base64(annotated)
    if parsed.include_depth:
        extras["depth_png_b64"] = _png_base64(draw_depth_map(artifacts.depth_map.depth))
        extras["depth_range_m"] = artifacts.depth_map.stats()

    extras["analytics"] = scene_analytics(scene).summary()

    metrics = get_metrics()
    metrics.record_scene(scene)
    metrics.record_request("/v1/measure", 200, time.perf_counter() - started)

    return _build_response(scene, getattr(request.state, "request_id", None), extras)


@router.post(
    "/measure/batch",
    summary="Measure several images in one request",
    response_description="One result per input image, in order",
)
async def measure_batch(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
    files: Annotated[list[UploadFile], File(description="Image files")],
    options: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Measure a batch of images.

    Per-image failures do not fail the batch: each result carries either a
    scene or an ``error`` object, so one corrupt upload cannot discard the
    work done on the rest.
    """
    started = time.perf_counter()
    if len(files) > _MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"batch of {len(files)} exceeds the limit of {_MAX_BATCH}",
        )

    parsed = _parse_options(options)
    previous = _apply_overrides(state, parsed)
    results: list[dict[str, Any]] = []

    try:
        for index, upload in enumerate(files):
            name = upload.filename or f"image_{index}"
            try:
                data = await upload.read()
                enforce_upload_limit(state, len(data), name)
                image = decode_image_bytes(data)
                frame = Frame(image=image, index=index, timestamp=time.time(), source_id=name)
                scene = state.pipeline.measure_frame(frame, track=False)
                get_metrics().record_scene(scene)
                results.append({"filename": name, "scene": scene.to_dict()})
            except HTTPException:
                raise
            except Exception as exc:
                log.warning("batch_item_failed", filename=name, error=str(exc))
                results.append(
                    {"filename": name, "error": {"code": "measurement_failed", "message": str(exc)}}
                )
    finally:
        _restore_overrides(state, previous)

    get_metrics().record_request("/v1/measure/batch", 200, time.perf_counter() - started)
    succeeded = sum(1 for r in results if "scene" in r)
    return {
        "request_id": getattr(request.state, "request_id", None),
        "count": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.post(
    "/measure/video",
    summary="Measure a video file",
    response_description="Per-frame measurements plus a run summary",
)
async def measure_video(
    request: Request,
    state: Annotated[AppState, Depends(get_state)],
    file: Annotated[UploadFile, File(description="Video file")],
    max_frames: Annotated[int, Form(ge=1, le=3600)] = 300,
    stride: Annotated[int, Form(ge=1, le=60)] = 1,
    options: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Measure a video with tracking and temporal fusion.

    Bounded by ``max_frames`` because this is a synchronous request. For long
    videos use the CLI (``measurecv video``), which streams results to disk
    instead of holding them in memory and returning them all at once.
    """
    import tempfile
    from pathlib import Path

    started = time.perf_counter()
    parsed = _parse_options(options)

    data = await file.read()
    enforce_upload_limit(state, len(data), file.filename or "video")

    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    tmp_path: Path | None = None
    scenes: list[dict[str, Any]] = []

    previous = _apply_overrides(state, parsed)
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data)
            tmp_path = Path(handle.name)

        pipeline = state.pipeline
        pipeline.reset_state()
        for scene, _frame in pipeline.process_video(tmp_path, max_frames=max_frames, stride=stride):
            get_metrics().record_scene(scene)
            scenes.append(scene.to_dict())
    finally:
        _restore_overrides(state, previous)
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    tracks: dict[int, dict[str, Any]] = {}
    for scene_dict in scenes:
        for obj in scene_dict["objects"]:
            track_id = obj["detection"].get("track_id")
            if track_id is None:
                continue
            entry = tracks.setdefault(
                track_id, {"track_id": track_id, "label": obj["detection"]["label"], "frames": 0}
            )
            entry["frames"] += 1
            # The last observation is the temporally fused one, so it is the
            # best single answer for the track.
            entry["final"] = obj.get("dimensions")

    get_metrics().record_request("/v1/measure/video", 200, time.perf_counter() - started)
    return {
        "request_id": getattr(request.state, "request_id", None),
        "frames": len(scenes),
        "duration_s": round(time.perf_counter() - started, 2),
        "tracks": sorted(tracks.values(), key=lambda t: -t["frames"]),
        "scenes": scenes,
    }
