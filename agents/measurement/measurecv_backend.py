"""
Agent 2 — metric object dimensioning, backed by the in-repo `measurecv` package.

This is the second half of Agent 2. The existing modules answer "how far apart
are these two rebar?" by establishing a pixels-to-millimetres scale and doing
2-D geometry on it. That is the right tool for a repeated linear pattern, and it
is what `estimator.py` does.

It cannot answer "how big is that duct / panel / spoil heap, and how far away is
it?", because a single px/mm scale is only valid at one depth. `measure/` solves
exactly that problem properly:

    RT-DETR detection -> SAM 2 masks -> Metric3D metric depth
      -> support-plane world frame -> oriented box -> L x W x H, volume, distance

and — the part that matters for a compliance system — it propagates uncertainty
through all of it, so every number arrives with a sigma and a 95% interval
rather than a bare float. Agent 3 can then refuse to issue a STOP WORK when the
tolerance boundary falls inside the error bar, instead of flipping a verdict on
noise.

Two things this module deliberately does NOT do:

  * It never falls back to measurecv's synthetic backends. Those exist as test
    doubles for the offline test suite and they render a self-consistent fake
    scene — exactly the "plausible number from a model that never ran" failure
    the guardrails forbid. If the real weights are missing, `available()` is
    False and callers get a refusal, not a fabrication.
  * It never blocks a live frame on a model download. Loading happens once,
    behind a lock, and a failure is latched so a 500 MB fetch is not retried
    per-frame.

Env:
    MEASURECV_ENABLED    '0' to hard-disable (low-RAM demo laptop)
    MEASURECV_CONFIG     path to a measurecv YAML. Default: measure/configs/cpu.yaml
                         Use configs/gpu.yaml on a CUDA box, configs/realtime.yaml
                         for streaming.
    MEASURECV_DEVICE     'cuda' | 'cpu' — overrides the config's runtime.device
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

# measure/ lives inside this repo; the package is installed editable from there.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "measure" / "configs" / "cpu.yaml"

MEASURECV_ENABLED = os.getenv("MEASURECV_ENABLED", "1") != "0"
MEASURECV_CONFIG = os.getenv("MEASURECV_CONFIG") or str(DEFAULT_CONFIG)
MEASURECV_DEVICE = os.getenv("MEASURECV_DEVICE")

# A synthetic backend produces numbers that look completely normal — correct
# units, sensible magnitudes, a confidence score — while measuring a scene that
# does not exist. Refusing them here is what keeps "measurement failed" and
# "measurement is fictional" from looking identical downstream.
_FORBIDDEN_BACKEND = "synthetic"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "loaded": False,
    "failed": False,
    "pipeline": None,
    "config_path": MEASURECV_CONFIG,
    "error": None,
    "load_seconds": None,
    "backends": None,
}


def _load() -> None:
    """Build the pipeline once. Latches failure so we never retry a big download
    on a per-frame path."""
    if _state["loaded"] or _state["failed"]:
        return
    with _lock:
        if _state["loaded"] or _state["failed"]:
            return
        if not MEASURECV_ENABLED:
            _state.update(failed=True, error="disabled via MEASURECV_ENABLED=0")
            return
        try:
            from measurecv import MeasurementPipeline, load_config

            cfg_path = Path(MEASURECV_CONFIG)
            if not cfg_path.exists():
                raise FileNotFoundError(
                    f"measurecv config not found: {cfg_path}. Set MEASURECV_CONFIG "
                    f"or restore {DEFAULT_CONFIG.relative_to(REPO_ROOT)}."
                )

            overrides: dict[str, Any] = {}
            if MEASURECV_DEVICE:
                overrides["runtime"] = {"device": MEASURECV_DEVICE}
            config = load_config(cfg_path, **overrides) if overrides else load_config(cfg_path)

            backends = {
                "detection": config.detection.backend,
                "segmentation": config.segmentation.backend,
                "depth": config.depth.backend,
            }
            fake = [k for k, v in backends.items() if v == _FORBIDDEN_BACKEND]
            if fake:
                raise RuntimeError(
                    f"refusing to serve measurements from synthetic backend(s): "
                    f"{', '.join(fake)}. These are test doubles that render a fake "
                    f"scene; their output is not a measurement. Point "
                    f"MEASURECV_CONFIG at a real-weights config."
                )

            t0 = time.time()
            print(f"[MEASURECV] loading pipeline from {cfg_path.name} "
                  f"(detection={backends['detection']}, depth={backends['depth']})…")
            pipeline = MeasurementPipeline(config)

            _state.update(
                pipeline=pipeline,
                loaded=True,
                backends=backends,
                load_seconds=round(time.time() - t0, 2),
                config_path=str(cfg_path),
            )
            print(f"[MEASURECV] pipeline ready in {_state['load_seconds']}s "
                  f"(weights load lazily on first frame)")
        except Exception as e:  # noqa: BLE001 — any failure means "unavailable"
            _state.update(failed=True, error=f"{type(e).__name__}: {e}")
            print(f"[MEASURECV] ⚠ unavailable ({e}). Object dimensioning is off; "
                  f"spacing measurement via ArUco/reference is unaffected.")


def available() -> bool:
    _load()
    return bool(_state["loaded"])


def status() -> dict[str, Any]:
    """Configuration and liveness — safe to call without triggering a load."""
    out: dict[str, Any] = {
        "enabled": MEASURECV_ENABLED,
        "loaded": _state["loaded"],
        "failed": _state["failed"],
        "config": _state["config_path"],
        "error": _state["error"],
        "load_seconds": _state["load_seconds"],
        "backends": _state["backends"],
    }
    if _state["loaded"]:
        try:
            out["stats"] = _state["pipeline"].stats()
        except Exception as e:  # noqa: BLE001
            out["stats_error"] = str(e)
    return out


def _bgr_to_rgb(image_bgr: np.ndarray) -> np.ndarray:
    """FieldPilot decodes frames with cv2 (BGR); measurecv expects RGB.

    Getting this backwards does not raise — RT-DETR still detects *something*
    and the geometry still runs, so the failure mode is a silently degraded
    detection rather than an error. Hence the explicit conversion here rather
    than relying on any caller to remember.
    """
    return np.ascontiguousarray(image_bgr[:, :, ::-1])


# ---------------------------------------------------------------------------
# Object dimensioning
# ---------------------------------------------------------------------------

def measure_objects(
    image_bgr: np.ndarray,
    *,
    labels: Optional[list[str]] = None,
    min_confidence: float = 0.0,
    max_objects: int = 20,
) -> dict[str, Any]:
    """Dimension every object measurecv can find in the frame.

    Args:
        image_bgr: OpenCV-order frame.
        labels: Restrict to these RT-DETR/COCO labels (case-insensitive).
        min_confidence: Drop objects the engine is less sure of than this.
        max_objects: Cap the response size.

    Returns:
        The Agent 2 dimensioning payload. `status` is one of:
            success        — at least one object measured
            no_measurement — pipeline ran, found nothing measurable
            unavailable    — real weights missing/disabled; no numbers invented
            error          — bad input
    """
    t0 = time.time()

    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return {"status": "error", "message": "empty image", "objects": []}

    if not available():
        return {
            "status": "unavailable",
            "message": "metric dimensioning is not available in this deployment",
            "detail": status(),
            "remedy": "pip install -e ./measure[models] timm mmengine, then restart. "
                      "Spacing/clearance via ArUco or a reference object still works.",
            "objects": [],
            "processing_time_ms": int((time.time() - t0) * 1000),
        }

    try:
        scene = _state["pipeline"].measure_image(_bgr_to_rgb(image_bgr))
    except Exception as e:  # noqa: BLE001
        return {
            "status": "error",
            "message": f"measurecv inference failed: {type(e).__name__}: {e}",
            "objects": [],
            "processing_time_ms": int((time.time() - t0) * 1000),
        }

    wanted = {s.lower() for s in labels} if labels else None
    objects: list[dict[str, Any]] = []

    for obj in scene.objects:
        label = obj.detection.label
        if wanted is not None and label.lower() not in wanted:
            continue
        if obj.confidence < min_confidence:
            continue
        objects.append(_object_payload(obj))
        if len(objects) >= max_objects:
            break

    objects.sort(key=lambda o: o["confidence"], reverse=True)

    payload: dict[str, Any] = {
        "status": "success" if objects else "no_measurement",
        "objects": objects,
        "object_count": len(objects),
        # This is the single most important field in the response: it says how
        # far the absolute scale can be trusted. `assumed_fov` means ~15%.
        "calibration_source": scene.calibration_source,
        "scale_accuracy": _SCALE_ACCURACY.get(scene.calibration_source, "unknown"),
        "ground_plane_found": scene.ground_plane is not None,
        "warnings": list(scene.warnings),
        "image_size": {"width": scene.image_size[0], "height": scene.image_size[1]},
        "timings_ms": {k: round(v, 1) for k, v in scene.timings_ms.items()},
        "processing_time_ms": int((time.time() - t0) * 1000),
    }
    if not objects:
        payload["message"] = (
            "no measurable object found. The detector recognises the 80 COCO "
            "classes; construction-specific assets (rebar mats, formwork, "
            "ducting) are not among them and need a fine-tuned detector."
        )
    return payload


_SCALE_ACCURACY = {
    "calibrated": "1-2% (target-based calibration)",
    "exif": "~5% (derived from image metadata)",
    "provided": "as supplied by caller",
    "assumed_fov": "~15% — NO CALIBRATION; treat as indicative, not metrology",
}


def _mm(measured: Any) -> Optional[dict[str, Any]]:
    """Convert a measurecv `Measured` (metres) into the millimetre payload the
    rest of FieldPilot speaks, keeping the error bar attached.

    Every consumer downstream — the compliance validator, the RFI drafter, the
    dashboard — works in mm because that is the unit construction tolerances are
    written in. Dropping sigma during the conversion would silently discard the
    whole reason for using this engine.
    """
    if measured is None:
        return None
    return {
        "value_mm": round(measured.value * 1000.0, 1),
        "sigma_mm": round(measured.sigma * 1000.0, 1),
        "relative_error": round(measured.relative_error, 4),
        "interval_95_mm": [round(v * 1000.0, 1) for v in measured.interval(1.96)],
        "confidence": round(measured.confidence, 3),
        "method": measured.method.value if measured.method else None,
    }


def _object_payload(obj: Any) -> dict[str, Any]:
    d = obj.dimensions
    bbox = obj.detection.bbox
    return {
        "label": obj.detection.label,
        "score": round(obj.detection.score, 3),
        "track_id": obj.track_id,
        "bbox_px": [round(v, 1) for v in bbox.as_tuple()],
        "dimensions_mm": {
            "length": _mm(d.length) if d else None,
            "width": _mm(d.width) if d else None,
            "height": _mm(d.height) if d else None,
        } if d else None,
        "volume_litres": _volume_litres(obj.volume),
        "distance_mm": _mm(obj.distance),
        "nearest_distance_mm": _mm(obj.nearest_distance),
        "confidence": round(obj.confidence, 3),
        "point_count": obj.point_count,
        "mask_area_px": obj.mask_area_px,
        # Surfaced verbatim, never summarised away: "object touches the frame
        # border; measurements are lower bounds" is the difference between a
        # measurement and a guess, and the worker needs to see it.
        "warnings": list(obj.warnings),
    }


def _volume_litres(volume: Any) -> Optional[dict[str, Any]]:
    if volume is None:
        return None
    return {
        "value": round(volume.value * 1000.0, 2),
        "sigma": round(volume.sigma * 1000.0, 2),
        "relative_error": round(volume.relative_error, 4),
        "confidence": round(volume.confidence, 3),
        "method": volume.method.value if volume.method else None,
        "caveat": "single-viewpoint inference — the back of the object is never "
                  "observed; concave shapes read high",
    }


# ---------------------------------------------------------------------------
# Metric depth provider for the existing calibration ladder
# ---------------------------------------------------------------------------

def estimate_metric_depth(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """Metric depth in METRES at the input frame's resolution, or None.

    Drop-in replacement for `agents.measurement.depth.estimate_depth`, but
    routed through Metric3D with measurecv's canonical-camera transform applied.
    That transform is the whole ballgame for metric accuracy: Metric3D predicts
    in a canonical space with a fixed 1000 px focal length, and raw output must
    be rescaled by `f_real * resize_scale / 1000`. Skipping it yields a depth map
    that is smooth, correctly ordered and confidently wrong by the ratio of the
    real focal length to 1000 — around 40% on a typical phone camera, with
    nothing in the output to indicate a problem.

    Returned at the ORIGINAL resolution: measurecv works internally on a
    downscaled frame (runtime.max_image_side), and `calibrate_from_depth`
    indexes the map with full-resolution pixel coordinates.

    Only the depth stage runs. Going through `measure_frame_full` would also
    pay for RT-DETR and SAM 2 — on this laptop that is ~12s of detection and
    segmentation whose masks the calibration ladder then throws away.
    """
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        return None
    if not available():
        return None

    try:
        import cv2

        pipeline = _state["pipeline"]
        rgb = _bgr_to_rgb(image_bgr)
        h, w = rgb.shape[:2]

        # Mirror MeasurementPipeline._prepare: resolve intrinsics at the native
        # resolution (so any EXIF/profile focal length is interpreted against
        # the size it describes) and only then downscale, rescaling the camera
        # to match. Metric3D needs the focal length that belongs to the image
        # it is actually given; handing it the full-res one after a resize
        # scales every depth by the resize factor.
        camera = pipeline.resolver.resolve(w, h, exif={}, override=None)

        max_side = pipeline.config.runtime.max_image_side
        proc = rgb
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            new_w, new_h = round(w * scale), round(h * scale)
            proc = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            camera = camera.scaled(new_w, new_h)

        with pipeline.models.inference_slot():
            depth_map = pipeline.models.depth_estimator.estimate(proc, camera)

        if depth_map is None:
            return None
        depth = np.asarray(depth_map.depth, dtype=np.float32)

        if depth.shape != (h, w):
            depth = cv2.resize(depth, (w, h), interpolation=cv2.INTER_LINEAR)
        return depth
    except Exception as e:  # noqa: BLE001
        print(f"[MEASURECV] depth inference failed: {e}")
        return None
