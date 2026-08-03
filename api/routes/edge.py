"""
Edge inference API — the offline/NPU path.

Two purposes:

  GET  /edge/status   what the on-device runtime is, which execution provider it
                      resolved to, and whether an NPU is actually being used.
                      The mobile app calls this to decide whether to run locally
                      or defer to the cloud.
  POST /edge/detect   run the edge model server-side. Used to verify the exact
                      code path the phone runs, and as the fallback when a phone
                      is too old to host ONNX Runtime at all.

The phone does NOT normally call /edge/detect — that would defeat the point of
edge inference. It runs the same model locally via onnxruntime-react-native and
only posts RESULTS, through the offline queue, when connectivity returns.
"""

from __future__ import annotations

import base64
import os
import sys
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.edge.runtime import get_detector

router = APIRouter(prefix="/api/v1/edge", tags=["Edge / NPU Inference"])


@router.get("/status")
async def edge_status():
    """Runtime, model, provider, and whether NPU acceleration is genuinely active.

    npu_accelerated is deliberately a real check of the resolved provider rather
    than a claim: on a desktop build of onnxruntime only CPU exists, so it
    reports false here and the note explains why.
    """
    return get_detector().status()


class DetectRequest(BaseModel):
    frame: str = Field(..., description="base64 JPEG/PNG, data: prefix optional")
    conf_threshold: Optional[float] = Field(None, ge=0.01, le=0.99)
    include_annotated: bool = False


@router.post("/detect")
async def edge_detect(req: DetectRequest):
    payload = req.frame.split(",", 1)[-1] if "," in req.frame else req.frame
    try:
        raw = base64.b64decode(payload)
    except Exception as e:
        raise HTTPException(400, f"invalid base64: {e}")

    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, "could not decode image")

    det = get_detector()
    if not det.ready:
        raise HTTPException(503, det.load_error or "edge runtime unavailable")

    if req.conf_threshold is not None:
        original = det.conf_threshold
        det.conf_threshold = req.conf_threshold
        try:
            result = det.detect(image)
        finally:
            det.conf_threshold = original
    else:
        result = det.detect(image)

    payload_out = result.as_dict()

    if req.include_annotated:
        annotated = image.copy()
        for d in result.detections:
            x1, y1, x2, y2 = (int(v) for v in d.bbox)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 200, 80), 2)
            cv2.putText(annotated, f"{d.confidence:.2f}", (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 80), 1)
            for kx, ky, kc in d.keypoints:
                if kc > 0.4:
                    cv2.circle(annotated, (int(kx), int(ky)), 3, (0, 255, 255), -1)
        for h in result.hazards:
            if h.get("severity") == "critical":
                cv2.putText(annotated, f"! {h['type']}", (12, 30),
                            cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 0, 255), 2)
                break
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            payload_out["annotated_frame_b64"] = base64.b64encode(buf).decode()

    return payload_out


@router.get("/benchmarks")
async def edge_benchmarks():
    """The most recent measured comparison, so the dashboard can state real
    numbers instead of a marketing figure."""
    import glob
    import json

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    files = sorted(glob.glob(os.path.join(root, "models", "evaluation",
                                          "edge_benchmark_*.json")))
    if not files:
        return {"available": False,
                "hint": "run: python scripts/benchmark_edge.py"}
    with open(files[-1], "r", encoding="utf-8") as f:
        report = json.load(f)
    return {"available": True, "source_file": os.path.basename(files[-1]), **report}
