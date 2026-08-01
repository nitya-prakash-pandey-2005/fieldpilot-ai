"""
Monocular metric depth for Agent 2 — Depth Anything V2.

Uses the released METRIC checkpoints, not the relative-depth ones. The relative
model outputs inverse depth in arbitrary units, which cannot be turned into
millimetres without a second scale source; the metric checkpoints output actual
metres, which is what calibration.calibrate_from_depth needs.

Model is lazy-loaded on first use and cached process-wide. On a machine with no
torch/transformers, or with no model cached and no network, `available()`
returns False and the measurement engine falls back to ArUco/reference — it
never blocks a live frame waiting on a download.

Env:
    DEPTH_MODEL_ID    HF id. Default is the indoor metric Small checkpoint,
                      which runs at a usable speed on CPU. Use the Large indoor
                      checkpoint on GPU for best accuracy; use an Outdoor
                      checkpoint for open-air sites (it is trained on a very
                      different depth range and gets indoor scenes badly wrong).
    DEPTH_DEVICE      'cuda' | 'cpu' | 'auto' (default auto)
    DEPTH_ENABLED     set '0' to hard-disable (e.g. on a low-RAM demo laptop)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

import numpy as np

DEFAULT_MODEL = os.getenv(
    "DEPTH_MODEL_ID",
    "depth-anything/Depth-Anything-V2-metric-indoor-small-hf",
)
DEPTH_DEVICE = os.getenv("DEPTH_DEVICE", "auto")
DEPTH_ENABLED = os.getenv("DEPTH_ENABLED", "1") != "0"

_lock = threading.Lock()
_state: dict = {"loaded": False, "failed": False, "pipe": None, "device": None, "error": None}


def _resolve_device() -> str:
    if DEPTH_DEVICE != "auto":
        return DEPTH_DEVICE
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load():
    """Load once. Marks itself permanently failed on error so a live pipeline
    doesn't retry a 300MB download on every single frame."""
    if _state["loaded"] or _state["failed"]:
        return
    with _lock:
        if _state["loaded"] or _state["failed"]:
            return
        if not DEPTH_ENABLED:
            _state.update(failed=True, error="disabled via DEPTH_ENABLED=0")
            return
        try:
            from transformers import pipeline
            device = _resolve_device()
            t0 = time.time()
            print(f"[DEPTH] loading {DEFAULT_MODEL} on {device}…")
            _state["pipe"] = pipeline(
                task="depth-estimation",
                model=DEFAULT_MODEL,
                device=0 if device == "cuda" else -1,
            )
            _state["device"] = device
            _state["loaded"] = True
            print(f"[DEPTH] ready in {time.time() - t0:.1f}s")
        except Exception as e:
            _state.update(failed=True, error=str(e))
            print(f"[DEPTH] ⚠ unavailable ({e}). Measurement falls back to ArUco/reference.")


def available() -> bool:
    _load()
    return bool(_state["loaded"])


def status() -> dict:
    return {
        "enabled": DEPTH_ENABLED,
        "loaded": _state["loaded"],
        "failed": _state["failed"],
        "model": DEFAULT_MODEL,
        "device": _state["device"],
        "error": _state["error"],
    }


def estimate_depth(image_bgr: np.ndarray, max_side: int = 700) -> Optional[np.ndarray]:
    """Return a metric depth map in METRES, same H×W as the input frame.

    Downscales before inference (depth is smooth, so this costs almost no
    accuracy) then resamples back up — full-resolution inference on a 4K glasses
    frame is several seconds on CPU and blows the <5s end-to-end alert budget in
    system_prompt.md §13.1.
    """
    _load()
    if not _state["loaded"]:
        return None

    try:
        import cv2
        from PIL import Image

        h, w = image_bgr.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        small = cv2.resize(image_bgr, (int(w * scale), int(h * scale)),
                           interpolation=cv2.INTER_AREA) if scale < 1.0 else image_bgr

        pil = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        out = _state["pipe"](pil)

        # transformers returns {'predicted_depth': tensor, 'depth': PIL}. Use the
        # tensor: the PIL image is min-max normalised to 0-255 for visualisation
        # and has thrown the metric scale away.
        pred = out.get("predicted_depth")
        if pred is None:
            return None
        depth = pred.squeeze().detach().cpu().numpy().astype(np.float32)

        if depth.shape != (h, w):
            depth = cv2.resize(depth, (w, h), interpolation=cv2.INTER_LINEAR)
        return depth
    except Exception as e:
        print(f"[DEPTH] inference failed: {e}")
        return None


def colorize(depth: np.ndarray) -> Optional[np.ndarray]:
    """Depth map as a BGR image, for the dashboard's measurement evidence panel."""
    try:
        import cv2
        d = depth.copy()
        finite = d[np.isfinite(d) & (d > 0)]
        if finite.size == 0:
            return None
        lo, hi = float(np.percentile(finite, 2)), float(np.percentile(finite, 98))
        norm = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        return cv2.applyColorMap((norm * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    except Exception:
        return None
