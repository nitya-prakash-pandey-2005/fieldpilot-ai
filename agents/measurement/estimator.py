"""
Agent 2 — Physical Measurement Engine.

Extracts real-world metric measurements from a single frame, with no contact and
no laser. Orchestrates the three modules around it:

    calibration.py    pixels -> millimetres  (ArUco > reference object > depth)
    depth.py          Depth Anything V2 metric depth, for the no-props case
    rebar_spacing.py  the actual geometry: bar/element spacing, clearance, length

Calibration priority follows system_prompt.md §Agent-2:
    1. ArUco marker in frame        -> plane homography, ±1-2mm, conf ~0.95
    2. Known reference object       -> uniform scale,     ±5-8%,  conf ~0.70-0.85
    3. Monocular metric depth       -> intrinsics guess,  ±10-15%, conf ~0.60
    4. Nothing                      -> refuse to guess, return status 'uncalibrated'

Case 4 matters more than it looks. The previous version of this file always
returned a number — it measured "distance from image centre to the marker",
which is not a quantity anyone asked for, and it reported 0.98 confidence for
it. A measurement agent that fabricates a plausible number is worse than one
that says it cannot measure, because Agent 5 will happily issue a STOP WORK on
a fabricated deviation.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import cv2
import numpy as np

from agents.measurement.calibration import (
    ArucoCalibrator,
    Calibration,
    REFERENCE_OBJECTS_MM,
    calibrate_from_depth,
    calibrate_from_reference,
)
from agents.measurement import depth as depth_mod
from agents.measurement import measurecv_backend as mcv
from agents.measurement.rebar_spacing import (
    SpacingResult,
    annotate,
    measure_spacing,
)

# 'aruco'  — marker only, refuse otherwise (most accurate, needs a prop)
# 'hybrid' — the full priority ladder above (default; what the demo runs)
# 'depth'  — force the depth path, for testing it in isolation
DEPTH_BACKEND = os.getenv("DEPTH_BACKEND", "hybrid").lower()

# Which model supplies the metric depth map for rung 3 of the ladder.
#
#   'auto'          Metric3D via measurecv when its weights are present,
#                   Depth Anything V2 otherwise. Default.
#   'measurecv'     Metric3D only — refuse rung 3 if it is unavailable.
#   'depth_anything' DAV2 only, the pre-integration behaviour.
#
# Metric3D is preferred because measurecv applies the canonical-camera
# transform to its output. Both models emit "metric" depth, but Metric3D
# predicts in a canonical space with a fixed 1000px focal length, and the
# rescale by f_real/1000 is what actually makes the numbers metres. DAV2-metric
# skips that step entirely, so its scale is tied to the indoor/outdoor training
# distribution rather than to this camera.
DEPTH_PROVIDER = os.getenv("DEPTH_PROVIDER", "auto").lower()

SUPPORTED_TYPES = ("spacing", "clearance", "length", "diameter", "overlap", "angle")


class MeasurementEngine:
    """Instantiate once per process — the ArUco detector and the lazily-loaded
    depth model are both reusable and the depth model is expensive to build."""

    def __init__(self):
        self.aruco = ArucoCalibrator()

    # -- calibration ladder -------------------------------------------------

    def calibrate(self, image: np.ndarray,
                  reference_bbox: Optional[dict] = None,
                  reference_type: Optional[str] = None,
                  reference_length_mm: Optional[float] = None,
                  device: str = "webcam",
                  allow_depth: bool = True) -> Calibration:
        """Run the priority ladder and return the best calibration available.

        `allow_depth=False` stops the ladder after rung 2. Rung 3 costs ~5.6s of
        CPU inference, which is fine for an explicit capture and far too slow for
        the Edge-mode loop that is meant to model a phone. Disabling it makes the
        engine refuse (rung 4) rather than silently blocking the pipeline, which
        is the honest trade: no marker in frame means no measurement on device.
        """
        # 1 — ArUco
        if DEPTH_BACKEND in ("aruco", "hybrid"):
            calib = self.aruco.calibrate(image)
            if calib is not None:
                return calib
            if DEPTH_BACKEND == "aruco":
                return Calibration(method="none", confidence=0.0,
                                   detail={"reason": "no ArUco marker found and "
                                                     "DEPTH_BACKEND=aruco forbids fallback"})

        # 2 — known reference object
        if reference_bbox and (reference_type or reference_length_mm):
            calib = calibrate_from_reference(reference_bbox,
                                             reference_type or "custom",
                                             reference_length_mm)
            if calib is not None:
                return calib

        # 3 — monocular metric depth
        if allow_depth and DEPTH_BACKEND in ("hybrid", "depth", "depth_anything", "metric3d"):
            dmap, provider = self._estimate_depth(image)
            if dmap is not None:
                calib = calibrate_from_depth(dmap, image.shape, device=device)
                # Which network produced the depth changes how much the number
                # can be trusted, so it travels with the calibration rather than
                # being inferred from env vars at read time.
                calib.detail["depth_provider"] = provider
                return calib

        # 4 — refuse
        return Calibration(
            method="none", confidence=0.0,
            detail={"reason": "no ArUco marker, no reference object, and depth "
                              + ("estimation disabled for this call (allow_depth=False)"
                                 if not allow_depth else "estimation unavailable"),
                    "depth_allowed": allow_depth,
                    "depth_status": depth_mod.status(),
                    "remedy": "place a 100mm ArUco marker in frame "
                              "(python models/training/make_aruco.py), or pass "
                              "reference_type=hardhat with the worker's bbox"},
        )

    def _estimate_depth(self, image: np.ndarray) -> tuple[Optional[np.ndarray], str]:
        """Metric depth map plus the name of the model that produced it.

        Returns (None, reason) when no provider is available — the caller then
        drops to rung 4 and refuses to measure, which is the correct outcome.
        """
        if DEPTH_PROVIDER in ("auto", "measurecv", "metric3d"):
            dmap = mcv.estimate_metric_depth(image)
            if dmap is not None:
                return dmap, "metric3d(measurecv)"
            if DEPTH_PROVIDER != "auto":
                return None, "metric3d_unavailable"

        if DEPTH_PROVIDER in ("auto", "depth_anything", "dav2"):
            dmap = depth_mod.estimate_depth(image)
            if dmap is not None:
                return dmap, "depth_anything_v2"

        return None, "no_depth_provider_available"

    # -- public API ---------------------------------------------------------

    def measure(self,
                image: np.ndarray,
                measurement_type: str = "spacing",
                roi: Optional[tuple] = None,
                reference_bbox: Optional[dict] = None,
                reference_type: Optional[str] = None,
                reference_length_mm: Optional[float] = None,
                device: str = "webcam",
                want_annotated: bool = True,
                allow_depth: bool = True) -> dict:
        """Measure `measurement_type` in `image`. Returns the Agent 2 payload."""
        t0 = time.time()

        if image is None or image.size == 0:
            return {"status": "error", "message": "empty image"}
        if measurement_type not in SUPPORTED_TYPES:
            return {"status": "error",
                    "message": f"unsupported measurement_type {measurement_type!r}; "
                               f"supported: {', '.join(SUPPORTED_TYPES)}"}

        calib = self.calibrate(image, reference_bbox, reference_type,
                               reference_length_mm, device, allow_depth=allow_depth)

        if not calib.ok:
            return {
                "status": "uncalibrated",
                "message": "cannot convert pixels to millimetres in this frame",
                "calibration": {"method": "none", "confidence": 0.0, **calib.detail},
                "measurements": [],
                "processing_time_ms": int((time.time() - t0) * 1000),
            }

        if measurement_type in ("spacing", "clearance"):
            results = measure_spacing(image, calib, roi=roi)
            measurements = [self._to_measurement(r, measurement_type) for r in results]
        elif measurement_type == "length":
            measurements = self._measure_length(image, calib, roi)
        elif measurement_type == "diameter":
            measurements = self._measure_diameter(image, calib, roi)
        else:
            # overlap and angle need two explicitly identified assets from Agent 1;
            # the endpoint for that is measure_between().
            return {"status": "error",
                    "message": f"{measurement_type} requires two assets — "
                               f"use POST /api/v1/measurement/between",
                    "measurements": []}

        payload = {
            "status": "success" if measurements else "no_measurement",
            "measurement_type": measurement_type,
            "calibration": {
                "method": calib.method,
                "confidence": calib.confidence,
                "px_per_mm": round(calib.px_per_mm, 4) if calib.px_per_mm else None,
                **{k: v for k, v in calib.detail.items() if k not in ("cx", "cy")},
            },
            "measurements": measurements,
            "processing_time_ms": int((time.time() - t0) * 1000),
        }
        if not measurements:
            payload["message"] = (
                "calibration succeeded but no measurable structure was found. "
                "For spacing, the frame needs at least two roughly parallel "
                "elements spanning ~12% of the image."
            )

        if want_annotated:
            try:
                ann = annotate(image, results if measurement_type in ("spacing", "clearance") else [], calib)
                ok, buf = cv2.imencode(".jpg", ann, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    import base64
                    payload["annotated_frame_b64"] = base64.b64encode(buf).decode()
            except Exception as e:
                payload["annotation_error"] = str(e)

        return payload

    def measure_between(self, image: np.ndarray,
                        point_a: tuple[float, float],
                        point_b: tuple[float, float],
                        measurement_type: str = "length",
                        **calib_kwargs) -> dict:
        """Distance between two explicitly given image points.

        This is what Agent 1 calls when it has already localised two assets and
        wants the gap between them — the `{"between": ["rebar_1","rebar_2"]}`
        request shape in system_prompt.md's Agent 2 spec.
        """
        t0 = time.time()
        calib = self.calibrate(image, **calib_kwargs)
        if not calib.ok:
            return {"status": "uncalibrated", "calibration": calib.detail, "measurements": []}

        mm = calib.to_mm(point_a, point_b)
        if mm is None:
            return {"status": "no_measurement",
                    "message": "points fall outside the calibrated region "
                               "(for depth calibration, one of them has no valid depth)",
                    "measurements": []}

        return {
            "status": "success",
            "measurement_type": measurement_type,
            "calibration": {"method": calib.method, "confidence": calib.confidence},
            "measurements": [{
                "type": measurement_type,
                "value": round(mm, 1),
                "unit": "mm",
                "confidence": round(calib.confidence, 3),
                "method_used": f"{calib.method}_two_point",
                "endpoints_px": [list(point_a), list(point_b)],
            }],
            "processing_time_ms": int((time.time() - t0) * 1000),
        }

    # -- individual measurement types ---------------------------------------

    @staticmethod
    def _to_measurement(r: SpacingResult, measurement_type: str) -> dict:
        d = r.as_dict()
        d["type"] = measurement_type
        d["method_used"] = f"{d.pop('calibration')}_{d.pop('extraction')}"
        return d

    def _measure_length(self, image: np.ndarray, calib: Calibration,
                        roi: Optional[tuple]) -> list[dict]:
        """Longest straight element in the ROI — used for lap-splice / bar length."""
        from agents.measurement.rebar_spacing import _detect_segments, _preprocess

        off = (0, 0)
        img = image
        if roi:
            x1, y1, x2, y2 = (int(v) for v in roi)
            img = image[max(0, y1):y2, max(0, x1):x2]
            off = (max(0, x1), max(0, y1))
        if img.size == 0:
            return []

        segs = _detect_segments(_preprocess(img))
        if len(segs) == 0:
            return []

        best = max(segs, key=lambda s: (s[2] - s[0]) ** 2 + (s[3] - s[1]) ** 2)
        p1 = (float(best[0]) + off[0], float(best[1]) + off[1])
        p2 = (float(best[2]) + off[0], float(best[3]) + off[1])
        mm = calib.to_mm(p1, p2)
        if mm is None:
            return []
        return [{
            "type": "length", "value": round(mm, 1), "unit": "mm",
            # A length is a single observation with no consistency check
            # available, so it can never be as trustworthy as an n-sample median.
            "confidence": round(calib.confidence * 0.85, 3),
            "method_used": f"{calib.method}_longest_segment",
            "endpoints_px": [list(p1), list(p2)],
            "caveat": "longest detected straight edge in ROI — verify it is the "
                      "intended element before acting on it",
        }]

    def _measure_diameter(self, image: np.ndarray, calib: Calibration,
                          roi: Optional[tuple]) -> list[dict]:
        """Bar/pipe diameter via the perpendicular width of the dominant element."""
        from agents.measurement.rebar_spacing import (
            _cluster_orientations, _detect_segments, _merge_to_lines, _preprocess,
        )
        import math

        off = (0, 0)
        img = image
        if roi:
            x1, y1, x2, y2 = (int(v) for v in roi)
            img = image[max(0, y1):y2, max(0, x1):x2]
            off = (max(0, x1), max(0, y1))
        if img.size == 0:
            return []

        segs = _detect_segments(_preprocess(img))
        fams = _cluster_orientations(segs)
        if not fams:
            return []

        theta_deg, fam_segs = fams[0]
        diag = math.hypot(*img.shape[:2])
        # No merging here: the two edges of ONE bar are exactly the signal we
        # want, and _merge_to_lines' whole job is to collapse them together.
        lines = _merge_to_lines(theta_deg, fam_segs, diag * 0.0005)
        if len(lines) < 2:
            return []

        lines.sort(key=lambda l: l["rho"])
        nx, ny = lines[0]["normal"]
        widths = []
        for a, b in zip(lines, lines[1:]):
            d_px = b["rho"] - a["rho"]
            p1 = (a["mid"][0] + off[0], a["mid"][1] + off[1])
            p2 = (a["mid"][0] + nx * d_px + off[0], a["mid"][1] + ny * d_px + off[1])
            mm = calib.to_mm(p1, p2)
            if mm is not None and 2.0 < mm < 200.0:      # plausible bar/pipe range
                widths.append(mm)
        if not widths:
            return []

        val = float(np.median(widths))
        return [{
            "type": "diameter", "value": round(val, 1), "unit": "mm",
            "confidence": round(calib.confidence * 0.75, 3),
            "method_used": f"{calib.method}_edge_pair",
            "candidates_mm": [round(w, 1) for w in sorted(widths)[:10]],
            "caveat": "edge-pair width; a rusted or shadowed bar reads wide",
        }]

    # -- back-compat --------------------------------------------------------

    def estimate_measurements(self, image_path: str,
                              reference_length_mm: Optional[float] = None) -> dict:
        """Path-based entry point kept for api/routes/measurement.py and the
        existing tests. New code should call measure()."""
        image = cv2.imread(image_path)
        if image is None:
            return {"status": "error", "message": f"failed to read image: {image_path}"}
        return self.measure(image, measurement_type="spacing",
                            reference_length_mm=reference_length_mm)

    # -- object dimensioning (measurecv) ------------------------------------

    def measure_objects(self, image: np.ndarray, **kwargs) -> dict:
        """Metric L x W x H / volume / distance for discrete objects in frame.

        Complements `measure()` rather than replacing it. `measure()` handles
        repeated linear patterns (rebar spacing) via a pixels-to-mm scale;
        this handles discrete objects via full 3-D reconstruction, which is the
        only way to get a correct answer when the object spans a depth range.
        """
        return mcv.measure_objects(image, **kwargs)

    def status(self) -> dict:
        # Resolve availability first: it triggers the (cheap) pipeline
        # construction, so reading mcv.status() afterwards reports the state
        # that actually applies rather than the pre-load one.
        dimensioning_available = mcv.available()
        return {
            "agent": "measurement",
            "calibration_backend": DEPTH_BACKEND,
            "depth_provider": DEPTH_PROVIDER,
            "aruco": {"dict": os.getenv("ARUCO_DICT", "DICT_4X4_50"),
                      "marker_mm": float(os.getenv("ARUCO_MARKER_MM", "100.0"))},
            "depth": depth_mod.status(),
            "measurecv": mcv.status(),
            "rebar_model": os.getenv("REBAR_MODEL_PATH") or None,
            "reference_objects": sorted(REFERENCE_OBJECTS_MM),
            "supported_types": list(SUPPORTED_TYPES),
            "dimensioning": {
                "available": dimensioning_available,
                "returns": ["length", "width", "height", "volume", "distance"],
                "unit": "mm (volume in litres)",
                "uncertainty": "every value carries sigma and a 95% interval",
            },
        }
