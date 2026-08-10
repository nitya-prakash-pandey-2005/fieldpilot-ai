"""
Accuracy tests for Agent 2 (Physical Measurement).

These build synthetic scenes with EXACTLY known geometry, so the assertions are
real accuracy checks rather than "it returned something". A synthetic scene is
not a substitute for the tape-measure validation in docs/TRAINING_PLAN.md §4 —
it can't catch lens distortion or a curled marker — but it does catch the class
of bug that silently makes every measurement wrong by a constant factor, which
is the failure mode that matters most here.

Run:
    python -m pytest tests/unit/test_measurement.py -v
    python tests/unit/test_measurement.py          # standalone, no pytest needed
"""

from __future__ import annotations

import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Keep these tests hermetic and fast: no model downloads, ArUco path only.
#
# Best-effort only. Both backends read these at module import, so they take
# effect just when this file is imported before the backend is — true when this
# file runs alone, not guaranteed in a full-suite run. Any test whose CORRECTNESS
# depends on a provider being absent must stub that provider itself; these two
# lines are here to keep the suite fast, not to establish a precondition.
os.environ.setdefault("DEPTH_ENABLED", "0")
os.environ.setdefault("MEASURECV_ENABLED", "0")

from agents.measurement.calibration import ArucoCalibrator, calibrate_from_reference
from agents.measurement.estimator import MeasurementEngine
from agents.measurement.rebar_spacing import measure_spacing

# Synthetic world: 2 px per mm.
PX_PER_MM = 2.0
MARKER_MM = 100.0


def build_grid_scene(spacing_mm: float = 150.0,
                     bar_diameter_mm: float = 16.0,
                     n_bars: int = 7,
                     px_per_mm: float = PX_PER_MM,
                     with_marker: bool = True) -> np.ndarray:
    """A top-down rebar grid on a dark deck, with an ArUco marker lying in-plane."""
    spacing_px = spacing_mm * px_per_mm
    bar_px = max(2, int(round(bar_diameter_mm * px_per_mm)))
    margin = int(spacing_px)
    size = int(margin * 2 + spacing_px * (n_bars - 1))

    img = np.full((size, size, 3), 38, dtype=np.uint8)          # dark formwork
    img += np.random.default_rng(0).integers(-6, 6, img.shape, dtype=np.int16
                                             ).clip(-38, 60).astype(np.uint8)

    steel = (168, 172, 176)
    for i in range(n_bars):
        p = int(round(margin + i * spacing_px))
        cv2.line(img, (p, 0), (p, size), steel, bar_px)          # vertical bars
        cv2.line(img, (0, p), (size, p), steel, bar_px)          # horizontal bars

    if with_marker:
        d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        m_px = int(round(MARKER_MM * px_per_mm))
        marker = cv2.aruco.generateImageMarker(d, 0, m_px)
        pad = int(m_px * 0.25)
        tile = np.full((m_px + 2 * pad, m_px + 2 * pad), 255, np.uint8)
        tile[pad:pad + m_px, pad:pad + m_px] = marker
        tile_bgr = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        # bottom-right, clear of the bars we're measuring
        y0 = size - tile_bgr.shape[0] - 4
        x0 = size - tile_bgr.shape[1] - 4
        img[y0:y0 + tile_bgr.shape[0], x0:x0 + tile_bgr.shape[1]] = tile_bgr

    return img


def warp_perspective(img: np.ndarray, strength: float = 0.18) -> np.ndarray:
    """Simulate photographing the same plane from an angle."""
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dx = w * strength
    dst = np.float32([[dx, 0], [w - dx * 0.4, 0], [w, h], [0, h]])
    H = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, H, (w, h), borderValue=(38, 38, 38))


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------

def test_aruco_recovers_known_scale():
    img = build_grid_scene()
    calib = ArucoCalibrator().calibrate(img)
    assert calib is not None, "marker not detected in a clean synthetic scene"
    assert calib.method == "aruco"
    assert calib.confidence > 0.85

    # px_per_mm should match the scene we built to within 2%
    assert abs(calib.px_per_mm - PX_PER_MM) / PX_PER_MM < 0.02, \
        f"scale off: got {calib.px_per_mm:.4f}, expected {PX_PER_MM}"

    # A known 100mm span measured through the homography must come back 100mm.
    p1 = (100.0, 100.0)
    p2 = (100.0 + 100.0 * PX_PER_MM, 100.0)
    mm = calib.to_mm(p1, p2)
    assert abs(mm - 100.0) < 2.0, f"100mm span measured as {mm:.2f}mm"


def test_aruco_survives_perspective():
    """The whole point of using a homography instead of a px/mm scalar."""
    img = warp_perspective(build_grid_scene())
    calib = ArucoCalibrator().calibrate(img)
    assert calib is not None, "marker not detected under perspective"

    # The marker's own corners must still round-trip to a clean 100mm square.
    assert calib.detail["reprojection_residual_mm"] < 1.0
    assert calib.detail["skew_ratio"] > 1.0    # confirm the warp actually applied


def test_reference_object_calibration():
    calib = calibrate_from_reference({"x1": 100, "y1": 100, "x2": 380, "y2": 260},
                                     "hardhat")
    assert calib is not None and calib.method == "reference"
    # 280px across a nominal 280mm hard hat -> 1.0 px/mm
    assert abs(calib.px_per_mm - 1.0) < 0.01
    assert calib.confidence < 0.85, "reference-object path must not claim ArUco-grade confidence"


# ---------------------------------------------------------------------------
# spacing measurement
# ---------------------------------------------------------------------------

def _measured_spacing(img):
    calib = ArucoCalibrator().calibrate(img)
    assert calib is not None
    results = measure_spacing(img, calib)
    assert results, "no spacing measured on a clean synthetic grid"
    return results, calib


def test_spacing_accuracy_head_on():
    truth = 150.0
    img = build_grid_scene(spacing_mm=truth)
    results, _ = _measured_spacing(img)

    primary = results[0]
    err = abs(primary.median_mm - truth)
    assert err <= 5.0, (f"spacing error {err:.2f}mm exceeds the ±5mm target "
                        f"(measured {primary.median_mm:.2f}, truth {truth})")
    assert primary.count >= 3, "too few gaps measured to be a real median"
    assert primary.confidence >= 0.75, "confident measurement should clear Agent 5's threshold"


def test_spacing_detects_out_of_spec_grid():
    """The actual demo scenario: a 190mm grid against a 150mm ±10mm spec."""
    truth = 190.0
    img = build_grid_scene(spacing_mm=truth)
    results, _ = _measured_spacing(img)
    measured = results[0].median_mm

    assert abs(measured - truth) <= 6.0, f"measured {measured:.1f}, truth {truth}"
    # and it must actually fall outside the spec band, which is the whole point
    assert not (140.0 <= measured <= 160.0), \
        f"{measured:.1f}mm was not flagged as outside the 140-160mm tolerance"


def test_spacing_under_perspective():
    """A scalar px/mm would be badly wrong here; the homography should hold up."""
    truth = 150.0
    img = warp_perspective(build_grid_scene(spacing_mm=truth), strength=0.15)
    results, calib = _measured_spacing(img)

    # Looser bound than head-on: the warp puts bars at varying depth and the
    # synthetic warp itself is not a physically exact camera model.
    err = abs(results[0].median_mm - truth)
    assert err <= 15.0, f"perspective spacing error {err:.1f}mm (measured {results[0].median_mm:.1f})"


def test_both_grid_axes_measured():
    img = build_grid_scene(spacing_mm=150.0)
    results, _ = _measured_spacing(img)
    assert len(results) == 2, f"square grid should yield two axes, got {len(results)}"
    assert abs(results[0].median_mm - results[1].median_mm) < 12.0, \
        "a square grid's two axes should agree"


def test_thick_bar_relative_to_spacing():
    """Regression: a bar whose diameter is a large fraction of the spacing.

    Both edges of each bar get detected as separate lines. If they aren't merged
    back into one bar, the measurement returns the BAR DIAMETER instead of the
    spacing — which reads as a wildly out-of-spec value and would fire a false
    STOP WORK. A 16mm bar at 100mm spacing is 16% of the gap; the same bar at
    300mm is 5%, so no fixed tolerance separates them.
    """
    for truth, bar in ((100.0, 16.0), (120.0, 20.0), (150.0, 25.0)):
        img = build_grid_scene(spacing_mm=truth, bar_diameter_mm=bar)
        results, _ = _measured_spacing(img)
        measured = results[0].median_mm
        assert abs(measured - truth) <= 6.0, (
            f"{bar:.0f}mm bar at {truth:.0f}mm spacing measured {measured:.1f}mm "
            f"— bar edges likely not merged (returns ~{bar}mm when that happens)")


def test_outlier_rejection():
    """A missing bar creates a double-width gap; the median must absorb it."""
    truth = 150.0
    img = build_grid_scene(spacing_mm=truth, n_bars=8)
    # erase one vertical bar
    spacing_px = truth * PX_PER_MM
    p = int(round(spacing_px + 3 * spacing_px))
    cv2.line(img, (p, 0), (p, img.shape[0]), (38, 38, 38), int(16 * PX_PER_MM) + 6)

    results, _ = _measured_spacing(img)
    err = abs(results[0].median_mm - truth)
    assert err <= 8.0, (f"a single missing bar shifted the result by {err:.1f}mm — "
                        f"outlier rejection is not working")


# ---------------------------------------------------------------------------
# engine behaviour
# ---------------------------------------------------------------------------

def test_engine_end_to_end():
    engine = MeasurementEngine()
    img = build_grid_scene(spacing_mm=190.0)
    out = engine.measure(img, measurement_type="spacing")

    assert out["status"] == "success", out
    assert out["calibration"]["method"] == "aruco"
    assert out["measurements"], "no measurements returned"
    m = out["measurements"][0]
    assert m["unit"] == "mm"
    assert abs(m["value"] - 190.0) <= 6.0
    assert 0.0 < m["confidence"] <= 1.0
    assert out["processing_time_ms"] >= 0
    assert "annotated_frame_b64" in out, "evidence image missing"


def test_engine_refuses_when_uncalibrated():
    """The important negative case: no marker, no reference, depth disabled.

    The previous implementation returned a confident number here. Returning
    nothing is correct — Agent 5 escalates to STOP WORK on a FAIL, so a
    fabricated measurement becomes a fabricated work stoppage.

    Both depth providers are stubbed out explicitly rather than relying on the
    DEPTH_ENABLED / MEASURECV_ENABLED environment variables. Those are read at
    module import, so whether they take effect depends on which test file
    imported the backend first — which made this test pass alone and fail in a
    full run. The precondition belongs in the test, not in import order.
    """
    from agents.measurement import depth as _depth
    from agents.measurement import measurecv_backend as _mcv

    real_dav2, real_metric3d = _depth.estimate_depth, _mcv.estimate_metric_depth
    _depth.estimate_depth = lambda *a, **k: None
    _mcv.estimate_metric_depth = lambda *a, **k: None
    try:
        engine = MeasurementEngine()
        img = build_grid_scene(with_marker=False)
        out = engine.measure(img, measurement_type="spacing")
    finally:
        _depth.estimate_depth = real_dav2
        _mcv.estimate_metric_depth = real_metric3d

    assert out["status"] == "uncalibrated", f"expected refusal, got {out['status']}"
    assert out["measurements"] == []
    assert "remedy" in out["calibration"], "refusal should tell the user how to fix it"


def test_engine_rejects_unsupported_type():
    engine = MeasurementEngine()
    out = engine.measure(build_grid_scene(), measurement_type="volume")
    assert out["status"] == "error"
    assert "supported" in out["message"]


def test_measure_between_two_points():
    engine = MeasurementEngine()
    img = build_grid_scene()
    out = engine.measure_between(img, (100.0, 100.0), (100.0 + 200.0 * PX_PER_MM, 100.0))
    assert out["status"] == "success", out
    assert abs(out["measurements"][0]["value"] - 200.0) < 4.0


def test_status_reports_real_configuration():
    st = MeasurementEngine().status()
    assert st["agent"] == "measurement"
    assert "aruco" in st and st["aruco"]["marker_mm"] == 100.0
    assert "depth" in st and st["depth"]["enabled"] is False   # disabled at import


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}\n        {e}")
            failed += 1
        except Exception:
            print(f"  ERROR {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
