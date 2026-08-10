"""
Tests for the measurecv integration in Agent 2.

These are hermetic: no weights, no downloads, no GPU. They cover the two things
that can go wrong in an integration like this and would not be caught by
measurecv's own suite (which tests the engine, not how FieldPilot wires it):

  1. The refusal contract. When the real models are absent, the backend must
     say "unavailable" and return no numbers. The failure mode being guarded
     against is a plausible-looking measurement produced by a model that never
     ran — which is worse than an error, because it reaches Agent 5 and becomes
     a STOP WORK on a fabricated deviation.
  2. The unit boundary. measurecv works in metres, the rest of FieldPilot in
     millimetres, and the whole reason for using this engine is the error bar.
     A conversion that drops sigma silently turns a measurement with a stated
     ±12% into a bare number that reads as exact.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents.measurement import measurecv_backend as mcv


# ---------------------------------------------------------------------------
# Refusal contract
# ---------------------------------------------------------------------------

@pytest.fixture
def disabled(monkeypatch):
    """Force the backend into its unavailable state without touching weights."""
    monkeypatch.setattr(mcv, "MEASURECV_ENABLED", False)
    monkeypatch.setattr(
        mcv, "_state",
        {"loaded": False, "failed": True, "pipeline": None,
         "config_path": "test", "error": "disabled for test",
         "load_seconds": None, "backends": None},
    )


def test_reports_unavailable_rather_than_measuring(disabled):
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    out = mcv.measure_objects(img)

    assert out["status"] == "unavailable"
    assert out["objects"] == []
    # A refusal that does not say how to fix it just looks like a bug.
    assert "remedy" in out


def test_depth_provider_returns_none_when_unavailable(disabled):
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    assert mcv.estimate_metric_depth(img) is None


def test_empty_image_is_an_error_not_a_measurement():
    out = mcv.measure_objects(np.zeros((0, 0, 3), dtype=np.uint8))
    assert out["status"] == "error"
    assert out["objects"] == []


def test_synthetic_backends_are_refused(monkeypatch, tmp_path):
    """A synthetic backend renders a self-consistent fake scene.

    Its output has correct units, sensible magnitudes and a confidence score,
    so nothing downstream can tell it from a real measurement. The loader must
    refuse it outright rather than serve it.
    """
    cfg = tmp_path / "synthetic.yaml"
    cfg.write_text(
        "detection:\n  backend: synthetic\n"
        "segmentation:\n  backend: synthetic\n"
        "depth:\n  backend: synthetic\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mcv, "MEASURECV_ENABLED", True)
    monkeypatch.setattr(mcv, "MEASURECV_CONFIG", str(cfg))
    monkeypatch.setattr(
        mcv, "_state",
        {"loaded": False, "failed": False, "pipeline": None,
         "config_path": str(cfg), "error": None,
         "load_seconds": None, "backends": None},
    )

    assert mcv.available() is False
    assert "synthetic" in (mcv._state["error"] or "").lower()


# ---------------------------------------------------------------------------
# Unit boundary: metres -> millimetres, with the error bar intact
# ---------------------------------------------------------------------------

def test_metre_to_millimetre_conversion_preserves_uncertainty():
    from measurecv.core.types import Measured, MeasurementMethod, Unit

    m = Measured(value=0.4231, sigma=0.0219, unit=Unit.METRE,
                 method=MeasurementMethod.GROUND_ALIGNED, confidence=0.87)
    out = mcv._mm(m)

    assert out["value_mm"] == pytest.approx(423.1, abs=0.05)
    assert out["sigma_mm"] == pytest.approx(21.9, abs=0.05)

    # The interval must be the converted interval, not a re-derivation that
    # could quietly use a different coverage factor.
    lo, hi = out["interval_95_mm"]
    assert lo == pytest.approx(423.1 - 1.96 * 21.9, abs=0.2)
    assert hi == pytest.approx(423.1 + 1.96 * 21.9, abs=0.2)

    # Relative error is scale-free, so it must survive the unit change exactly.
    assert out["relative_error"] == pytest.approx(0.0219 / 0.4231, rel=1e-3)
    assert out["confidence"] == pytest.approx(0.87)
    assert out["method"] == "ground_aligned"


def test_none_quantity_converts_to_none():
    assert mcv._mm(None) is None


def test_bgr_to_rgb_actually_swaps_channels():
    """FieldPilot decodes with cv2 (BGR); measurecv expects RGB.

    Getting this backwards does not raise — the detector still finds
    *something* — so it can only be caught by asserting on the channel order.
    """
    bgr = np.zeros((2, 2, 3), dtype=np.uint8)
    bgr[:, :, 0] = 10   # blue
    bgr[:, :, 2] = 30   # red

    rgb = mcv._bgr_to_rgb(bgr)

    assert rgb[0, 0, 0] == 30, "red must land in channel 0"
    assert rgb[0, 0, 2] == 10, "blue must land in channel 2"
