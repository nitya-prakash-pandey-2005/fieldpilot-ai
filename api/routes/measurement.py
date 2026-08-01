"""
Agent 2 — Physical Measurement API.

Exposes the real measurement engine (agents/measurement/*): ArUco plane
homography, known-reference-object scaling, and monocular metric depth, feeding
spacing / clearance / length / diameter extraction.

Every endpoint can return status "uncalibrated" — that is a correct, expected
outcome, not an error. It means the frame contained nothing that establishes
scale, and the engine refuses to invent a number rather than handing Agent 5 a
fabricated deviation to issue a STOP WORK on. Callers must handle it; the
`calibration.remedy` field says how the worker fixes it.
"""

from __future__ import annotations

import base64
import os
import sys
import uuid
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.measurement.estimator import MeasurementEngine

router = APIRouter(prefix="/api/v1/measurement", tags=["Measurement Agent (Agent 2)"])

# One instance per process — the ArUco detector and the lazily-loaded depth model
# are both reusable and the depth model is expensive to construct.
engine = MeasurementEngine()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _decode(data: bytes) -> np.ndarray:
    """Decode straight from memory. The previous implementation wrote every
    upload to api/routes/temp_measurement/ under the CLIENT-supplied filename,
    which is both a path-traversal hazard and a race between concurrent workers
    posting the same filename."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not decode image — expected JPEG/PNG")
    return img


def _decode_b64(b64: str) -> np.ndarray:
    payload = b64.split(",", 1)[-1] if "," in b64 else b64
    try:
        return _decode(base64.b64decode(payload))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"invalid base64 image: {e}")


def _parse_roi(roi: Optional[str]) -> Optional[tuple]:
    if not roi:
        return None
    try:
        parts = [float(v) for v in roi.split(",")]
    except ValueError:
        raise HTTPException(400, "roi must be 'x1,y1,x2,y2'")
    if len(parts) != 4:
        raise HTTPException(400, "roi must have exactly 4 values: 'x1,y1,x2,y2'")
    return tuple(parts)


# ---------------------------------------------------------------------------
# multipart upload — used by the dashboard and the mobile app
# ---------------------------------------------------------------------------

@router.post("/measure")
async def measure_elements(
    file: UploadFile = File(...),
    measurement_type: str = Form("spacing"),
    roi: Optional[str] = Form(None, description="'x1,y1,x2,y2' to restrict to one asset"),
    reference_type: Optional[str] = Form(None, description="hardhat | brick | a4_sheet | ..."),
    reference_bbox: Optional[str] = Form(None, description="'x1,y1,x2,y2' of the reference object"),
    reference_length_mm: Optional[float] = Form(None),
    device: str = Form("webcam", description="webcam | phone | meta_glasses (sets assumed FOV)"),
    annotate: bool = Form(True),
):
    image = _decode(await file.read())

    ref_bbox = None
    if reference_bbox:
        b = _parse_roi(reference_bbox)
        ref_bbox = {"x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3]}

    result = engine.measure(
        image,
        measurement_type=measurement_type,
        roi=_parse_roi(roi),
        reference_bbox=ref_bbox,
        reference_type=reference_type,
        reference_length_mm=reference_length_mm,
        device=device,
        want_annotated=annotate,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "measurement failed"))

    result["job_id"] = str(uuid.uuid4())
    return result


# ---------------------------------------------------------------------------
# JSON / base64 — used by the live glasses + camera pipeline
# ---------------------------------------------------------------------------

class MeasureFrameRequest(BaseModel):
    frame: str = Field(..., description="base64 JPEG, with or without a data: prefix")
    measurement_type: str = "spacing"
    roi: Optional[list[float]] = None
    reference_type: Optional[str] = None
    reference_bbox: Optional[dict] = None
    reference_length_mm: Optional[float] = None
    device: str = "webcam"
    annotate: bool = False          # off by default: live frames don't need the echo


@router.post("/frame")
async def measure_frame(req: MeasureFrameRequest):
    image = _decode_b64(req.frame)
    result = engine.measure(
        image,
        measurement_type=req.measurement_type,
        roi=tuple(req.roi) if req.roi else None,
        reference_bbox=req.reference_bbox,
        reference_type=req.reference_type,
        reference_length_mm=req.reference_length_mm,
        device=req.device,
        want_annotated=req.annotate,
    )
    if result.get("status") == "error":
        raise HTTPException(400, result.get("message", "measurement failed"))
    return result


class MeasureBetweenRequest(BaseModel):
    frame: str
    point_a: list[float] = Field(..., min_length=2, max_length=2, description="[x, y] px")
    point_b: list[float] = Field(..., min_length=2, max_length=2, description="[x, y] px")
    measurement_type: str = "length"
    reference_type: Optional[str] = None
    reference_bbox: Optional[dict] = None
    device: str = "webcam"


@router.post("/between")
async def measure_between(req: MeasureBetweenRequest):
    """Distance between two points Agent 1 has already localised.

    This is the `{"between": ["rebar_1", "rebar_2"]}` request shape in
    system_prompt.md's Agent 2 spec, expressed in pixel coordinates.
    """
    image = _decode_b64(req.frame)
    return engine.measure_between(
        image,
        tuple(req.point_a),
        tuple(req.point_b),
        measurement_type=req.measurement_type,
        reference_type=req.reference_type,
        reference_bbox=req.reference_bbox,
        device=req.device,
    )


# ---------------------------------------------------------------------------
# validate — the full Agent 2 -> Agent 5 chain in one call
# ---------------------------------------------------------------------------

class MeasureAndValidateRequest(BaseModel):
    frame: str
    zone_id: str = "A12"
    asset_id: Optional[str] = None
    parameter: str = "spacing"
    expected_value: float = Field(..., description="spec value, mm")
    tolerance_min: float
    tolerance_max: float
    standard_ref: str = "ACI 318-19 §7.7.1"
    device: str = "webcam"
    worker_id: Optional[str] = None


@router.post("/validate")
async def measure_and_validate(req: MeasureAndValidateRequest):
    """Measure, then run the result straight through Agent 5's compliance check.

    This is the demo path: one call gives the measured value, the PASS/FAIL
    verdict, the severity, and the exact wording to speak into the worker's ear.
    """
    import time as _time

    from agents.compliance.validator import (
        ComplianceEngine, Measurement, Specification, ValidationRequest,
    )
    from routes.interactions import record_interaction

    _t0 = _time.time()
    image = _decode_b64(req.frame)
    measured = engine.measure(image, measurement_type=req.parameter,
                              device=req.device, want_annotated=True)

    if measured.get("status") != "success" or not measured.get("measurements"):
        # Surface the refusal verbatim rather than coercing it into a verdict.
        # It is still recorded: "the system could not measure this" is exactly
        # the kind of event an audit trail needs to show.
        await record_interaction(
            kind="measurement", worker_id=req.worker_id, zone_code=req.zone_id,
            query=f"Measure {req.parameter} (spec {req.expected_value}mm "
                  f"{req.tolerance_min}-{req.tolerance_max})",
            result=measured.get("message") or measured.get("status"),
            verdict="UNCERTAIN", agent_chain="A2:Measurement",
            latency_ms=round((_time.time() - _t0) * 1000, 1),
        )
        return {
            "measurement": measured,
            "validation": None,
            "verdict": "UNCERTAIN",
            "reason": measured.get("message") or measured.get("status"),
        }

    m = measured["measurements"][0]
    validation = await ComplianceEngine().validate(ValidationRequest(
        observation_id=str(uuid.uuid4()),
        asset_id=req.asset_id or f"{req.parameter}-{uuid.uuid4().hex[:8]}",
        zone_id=req.zone_id,
        measurement=Measurement(
            parameter=req.parameter,
            measured_value=float(m["value"]),
            unit=m.get("unit", "mm"),
            confidence=float(m.get("confidence", 0.0)),
        ),
        specification=Specification(
            spec_id=str(uuid.uuid4()),
            expected_value=req.expected_value,
            tolerance_min=req.tolerance_min,
            tolerance_max=req.tolerance_max,
            unit="mm",
            standard_ref=req.standard_ref,
        ),
    ))

    verdict = (validation or {}).get("result")
    explanation = (validation or {}).get("explanation") or {}
    await record_interaction(
        kind="measurement",
        worker_id=req.worker_id,
        zone_code=req.zone_id,
        query=f"Measure {req.parameter} (spec {req.expected_value}mm, "
              f"tolerance {req.tolerance_min}-{req.tolerance_max}mm)",
        result=explanation.get("worker_message")
               or f"{m['value']}{m.get('unit', 'mm')} measured",
        verdict=verdict,
        severity=(validation or {}).get("severity"),
        confidence=m.get("confidence"),
        agent_chain="A2:Measurement -> A5:Compliance"
                    + (" -> A9:Notify" if verdict == "FAIL" else ""),
        latency_ms=round((_time.time() - _t0) * 1000, 1),
    )

    return {"measurement": measured, "validation": validation, "verdict": verdict}


# ---------------------------------------------------------------------------

@router.get("/status")
async def measurement_status():
    """Real engine configuration — which calibration backends are actually live,
    whether the depth model loaded, whether a trained rebar model is wired in."""
    return engine.status()


@router.get("/marker")
async def get_calibration_marker():
    """The printable ArUco marker this deployment is calibrated for.

    Served from the API so a worker can pull it up on a phone and print it
    without needing the repo, and so it can never drift out of sync with
    ARUCO_DICT / ARUCO_MARKER_MM.
    """
    from fastapi.responses import Response

    dict_name = os.getenv("ARUCO_DICT", "DICT_4X4_50")
    size_mm = float(os.getenv("ARUCO_MARKER_MM", "100.0"))
    dpi = 300
    side_px = int(round(size_mm / 25.4 * dpi))

    dictionary = cv2.aruco.getPredefinedDictionary(
        getattr(cv2.aruco, dict_name, cv2.aruco.DICT_4X4_50))
    marker = cv2.aruco.generateImageMarker(dictionary, 0, side_px)
    pad = int(side_px * 0.22)
    canvas = np.full((side_px + 2 * pad, side_px + 2 * pad), 255, np.uint8)
    canvas[pad:pad + side_px, pad:pad + side_px] = marker
    cv2.putText(canvas, f"FieldPilot AI | {dict_name} id=0 | {size_mm:g} mm | PRINT AT 100%",
                (pad // 2, canvas.shape[0] - pad // 3), cv2.FONT_HERSHEY_SIMPLEX,
                side_px / 1400.0, 0, 2, cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", canvas)
    if not ok:
        raise HTTPException(500, "failed to encode marker")
    return Response(content=buf.tobytes(), media_type="image/png",
                    headers={"Content-Disposition": 'inline; filename="fieldpilot_aruco.png"'})
