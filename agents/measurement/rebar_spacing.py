"""
Rebar / conduit / cable-tray spacing measurement — the core of Agent 2.

This is the measurement behind the pitch deck's headline moment ("rebar spacing
190mm, spec 150mm ±10mm — STOP WORK"), so it is worth being explicit about how
it works and where it breaks.

Two independent extraction paths, both feeding the same metric conversion:

  LINE PATH (default, needs no trained model)
      Detects the bars themselves as line segments, clusters them into the two
      orthogonal families of a grid, merges duplicate detections of one bar, and
      measures the perpendicular gap between adjacent parallel bars. This is the
      literal definition of spacing and it works from the day you clone the repo.

  LATTICE PATH (uses REBAR_MODEL_PATH from training job T2)
      Detects grid intersections with the fine-tuned model and measures
      nearest-neighbour distances along each principal axis. More robust when
      bars are partially occluded by formwork or a worker's arm, because a
      missing bar segment doesn't delete the whole line.

Metric conversion always goes through calibration.Calibration.to_mm(), never
through a scalar px/mm — see calibration.py for why that distinction matters at
these tolerances.

Both paths report robust statistics (median + MAD, not mean + stddev). A single
mis-detected bar shifts a mean by tens of millimetres, and at a ±10mm tolerance
that is the difference between PASS and STOP WORK.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from agents.measurement.calibration import Calibration

REBAR_MODEL_PATH = os.getenv("REBAR_MODEL_PATH", "")

# A bar detected twice (both its edges) shows up as two lines a few pixels
# apart. Merge anything closer than this fraction of the image diagonal.
_MERGE_TOL_FRAC = 0.012
# Two orientation families must differ by at least this to count as a grid.
_MIN_AXIS_SEPARATION_DEG = 25.0


@dataclass
class SpacingResult:
    ok: bool
    axis: str                              # 'primary' | 'secondary'
    median_mm: Optional[float] = None
    mean_mm: Optional[float] = None
    mad_mm: Optional[float] = None         # median absolute deviation
    min_mm: Optional[float] = None
    max_mm: Optional[float] = None
    count: int = 0                         # number of gaps measured
    bar_count: int = 0
    confidence: float = 0.0
    samples_mm: list[float] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "value": round(self.median_mm, 1) if self.median_mm is not None else None,
            "unit": "mm",
            "statistic": "median",
            "mean_mm": round(self.mean_mm, 1) if self.mean_mm is not None else None,
            "mad_mm": round(self.mad_mm, 2) if self.mad_mm is not None else None,
            "min_mm": round(self.min_mm, 1) if self.min_mm is not None else None,
            "max_mm": round(self.max_mm, 1) if self.max_mm is not None else None,
            "gaps_measured": self.count,
            "bars_detected": self.bar_count,
            "confidence": round(self.confidence, 3),
            "samples_mm": [round(s, 1) for s in self.samples_mm],
            **self.detail,
        }


# ---------------------------------------------------------------------------
# Line extraction (classical, no model required)
# ---------------------------------------------------------------------------

def _preprocess(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    # Rebar on a dark formwork deck is a low-contrast scene; CLAHE recovers the
    # bar edges far better than a global equalisation.
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.bilateralFilter(gray, 7, 60, 60)     # denoise, keep edges crisp
    v = float(np.median(gray))
    lo = int(max(0, 0.66 * v))
    hi = int(min(255, 1.33 * v))
    return cv2.Canny(gray, lo, hi, apertureSize=3, L2gradient=True)


def _detect_segments(edges: np.ndarray) -> np.ndarray:
    h, w = edges.shape[:2]
    diag = math.hypot(h, w)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,                  # 0.5° resolution
        threshold=int(max(40, diag * 0.05)),
        minLineLength=int(diag * 0.12),     # a real bar spans a good part of frame
        maxLineGap=int(diag * 0.02),
    )
    return lines.reshape(-1, 4) if lines is not None else np.empty((0, 4))


def _cluster_orientations(segments: np.ndarray) -> list[tuple[float, np.ndarray]]:
    """Split segments into up to two dominant orientation families.

    Angles are taken mod 180° (a bar has no direction) and histogrammed. Naive
    circular-mean averaging fails at the 0/180 wrap, so angles near the seam are
    unwrapped relative to the peak before averaging.
    """
    if len(segments) < 4:
        return []

    ang = np.degrees(np.arctan2(segments[:, 3] - segments[:, 1],
                                segments[:, 2] - segments[:, 0])) % 180.0
    length = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])

    # Weight the histogram by segment length — a long bar is stronger evidence
    # of a real orientation than a short edge fragment.
    hist, edges_ = np.histogram(ang, bins=36, range=(0, 180), weights=length)

    families = []
    used = np.zeros(36, dtype=bool)
    for _ in range(2):
        hist_masked = np.where(used, 0, hist)
        if hist_masked.max() <= 0:
            break
        peak = int(np.argmax(hist_masked))
        peak_deg = (edges_[peak] + edges_[peak + 1]) / 2.0

        # unwrap around the seam, then take within ±15°
        delta = (ang - peak_deg + 90.0) % 180.0 - 90.0
        member = np.abs(delta) <= 15.0
        if member.sum() < 2:
            used[peak] = True
            continue

        mean_deg = float((peak_deg + np.average(delta[member], weights=length[member])) % 180.0)
        families.append((mean_deg, segments[member]))

        # suppress this peak and its ±15° neighbourhood before finding the next
        for b in range(36):
            centre = (edges_[b] + edges_[b + 1]) / 2.0
            if abs((centre - peak_deg + 90.0) % 180.0 - 90.0) <= 20.0:
                used[b] = True

    # Reject a "second axis" that is really just noise around the first.
    if len(families) == 2:
        sep = abs((families[0][0] - families[1][0] + 90.0) % 180.0 - 90.0)
        if sep < _MIN_AXIS_SEPARATION_DEG:
            families = [families[0]]

    return families


def _merge_to_lines(theta_deg: float, segs: np.ndarray, diag: float) -> list[dict]:
    """Collapse segments belonging to one bar into a single line.

    Each segment is reduced to its signed perpendicular offset `rho` from the
    origin along the family's normal. Segments of the same physical bar share a
    rho; two edges of one bar differ by the bar's diameter in pixels.
    """
    th = math.radians(theta_deg)
    nx, ny = -math.sin(th), math.cos(th)        # unit normal to the family

    entries = []
    for x1, y1, x2, y2 in segs:
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        entries.append({
            "rho": mx * nx + my * ny,
            "mid": (mx, my),
            "len": math.hypot(x2 - x1, y2 - y1),
            "pts": (float(x1), float(y1), float(x2), float(y2)),
        })
    entries.sort(key=lambda e: e["rho"])

    # Pass 1 — collapse near-identical detections of the same edge (and, when
    # the bar is thin relative to the frame, its two edges as well).
    tol = diag * _MERGE_TOL_FRAC
    merged: list[dict] = []
    group = [entries[0]]
    for e in entries[1:]:
        if e["rho"] - group[-1]["rho"] <= tol:
            group.append(e)
        else:
            merged.append(_collapse(group, nx, ny))
            group = [e]
    merged.append(_collapse(group, nx, ny))

    # Pass 2 — collapse each bar's two edges when pass 1's fixed tolerance was
    # too tight to catch them (a thick bar in a small frame: a 16mm bar at 100mm
    # spacing is 16% of the gap, and pass 1's image-relative tolerance has no way
    # to know that).
    #
    # A bar seen as two edges produces an ALTERNATING gap sequence
    # [diameter, clear_gap, diameter, clear_gap, ...]. Note the median is the
    # wrong statistic to split that: with an odd number of gaps the small
    # population is the majority, so the median lands inside it rather than
    # between the two. Instead, split where the sorted gaps show their largest
    # multiplicative jump — that is the boundary between the two populations,
    # and it exists only when there genuinely are two.
    for _ in range(4):
        if len(merged) < 4:
            break
        gaps = sorted(b["rho"] - a["rho"] for a, b in zip(merged, merged[1:]))
        if gaps[0] <= 0:
            break

        jump_at, best_ratio = -1, 1.0
        for k in range(len(gaps) - 1):
            ratio = gaps[k + 1] / max(gaps[k], 1e-6)
            if ratio > best_ratio:
                best_ratio, jump_at = ratio, k

        # Below ~2x there is only one population — the lines are already one
        # per bar and merging further would start eating real spacings.
        if best_ratio < 2.0 or jump_at < 0:
            break
        threshold = (gaps[jump_at] + gaps[jump_at + 1]) / 2.0

        collapsed: list[dict] = []
        i = 0
        while i < len(merged):
            if i + 1 < len(merged) and (merged[i + 1]["rho"] - merged[i]["rho"]) < threshold:
                collapsed.append(_collapse([merged[i], merged[i + 1]], nx, ny))
                i += 2                 # both edges of this bar consumed
            else:
                collapsed.append(merged[i])
                i += 1
        if len(collapsed) == len(merged):
            break
        merged = collapsed

    return merged


def _collapse(group: list[dict], nx: float, ny: float) -> dict:
    """Length-weighted representative of one bar.

    Accepts both raw segment entries (key 'len') and already-collapsed lines
    (key 'total_len'), because pass 2 of _merge_to_lines re-collapses its own
    pass-1 output.
    """
    w = np.array([float(g.get("len", g.get("total_len", 1.0))) for g in group],
                 dtype=np.float64)
    total = w.sum()
    w = w / total if total > 0 else np.full(len(group), 1.0 / len(group))
    rho = float(np.dot(w, [g["rho"] for g in group]))
    mx = float(np.dot(w, [g["mid"][0] for g in group]))
    my = float(np.dot(w, [g["mid"][1] for g in group]))
    return {"rho": rho, "mid": (mx, my), "normal": (nx, ny),
            "support": sum(int(g.get("support", 1)) for g in group),
            "total_len": float(sum(float(g.get("len", g.get("total_len", 0.0)))
                                   for g in group))}


# ---------------------------------------------------------------------------
# Lattice extraction (trained model path)
# ---------------------------------------------------------------------------

_lattice_model = None
_lattice_failed = False


def _load_lattice_model():
    global _lattice_model, _lattice_failed
    if _lattice_model is not None or _lattice_failed:
        return _lattice_model
    if not REBAR_MODEL_PATH or not os.path.exists(REBAR_MODEL_PATH):
        _lattice_failed = True
        return None
    try:
        from ultralytics import YOLO
        _lattice_model = YOLO(REBAR_MODEL_PATH)
        _lattice_model(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
        print(f"[REBAR] lattice model loaded: {REBAR_MODEL_PATH}")
    except Exception as e:
        print(f"[REBAR] ⚠ lattice model unavailable ({e}); using line path")
        _lattice_failed = True
    return _lattice_model


def _detect_lattice_points(image: np.ndarray, conf: float = 0.30) -> np.ndarray:
    model = _load_lattice_model()
    if model is None:
        return np.empty((0, 2))
    try:
        res = model.predict(image, verbose=False, conf=conf, imgsz=1280)
        pts = []
        for r in res:
            if r.boxes is None:
                continue
            for b in r.boxes:
                x1, y1, x2, y2 = b.xyxy[0].tolist()
                pts.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
        return np.array(pts, dtype=np.float64) if pts else np.empty((0, 2))
    except Exception as e:
        print(f"[REBAR] lattice inference failed: {e}")
        return np.empty((0, 2))


# ---------------------------------------------------------------------------
# Robust statistics
# ---------------------------------------------------------------------------

def _robust_stats(samples: list[float], reject_mad: float = 2.5) -> tuple[list[float], dict]:
    """Median/MAD outlier rejection.

    One bar missed by the detector produces a gap of exactly double the true
    spacing, and one spurious line produces a half-gap. Both are common and both
    are exactly the kind of error a mean absorbs and a median rejects.
    """
    if len(samples) < 3:
        return samples, {"outliers_rejected": 0}

    arr = np.array(samples, dtype=np.float64)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    if mad < 1e-6:
        return samples, {"outliers_rejected": 0}

    keep = np.abs(arr - med) <= reject_mad * mad * 1.4826   # 1.4826 -> ~sigma
    rejected = int((~keep).sum())
    if keep.sum() < 2:
        return samples, {"outliers_rejected": 0}
    return arr[keep].tolist(), {"outliers_rejected": rejected}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def measure_spacing(image: np.ndarray,
                    calib: Calibration,
                    prefer: str = "auto",
                    roi: Optional[tuple[int, int, int, int]] = None) -> list[SpacingResult]:
    """Measure element spacing in an image, in millimetres.

    Args:
        image:   BGR frame.
        calib:   a Calibration from agents.measurement.calibration. Must be `ok`.
        prefer:  'auto' | 'line' | 'lattice'. 'auto' tries the trained lattice
                 model if REBAR_MODEL_PATH is set, and falls back to lines.
        roi:     optional (x1, y1, x2, y2) to restrict measurement to one asset.

    Returns one SpacingResult per detected axis (a grid gives two: the primary
    axis is the one with more bars). Empty list if nothing measurable was found.
    """
    if not calib.ok:
        return []

    offset = (0, 0)
    if roi:
        x1, y1, x2, y2 = (int(v) for v in roi)
        x1, y1 = max(0, x1), max(0, y1)
        x2 = min(image.shape[1], x2)
        y2 = min(image.shape[0], y2)
        if x2 - x1 < 32 or y2 - y1 < 32:
            return []
        image = image[y1:y2, x1:x2]
        offset = (x1, y1)

    use_lattice = prefer == "lattice" or (prefer == "auto" and _load_lattice_model() is not None)
    if use_lattice:
        results = _measure_via_lattice(image, calib, offset)
        if results:
            return results
        # Model found nothing measurable (occlusion, wrong asset) — the line
        # path often still succeeds, so don't give up here.

    return _measure_via_lines(image, calib, offset)


def _measure_via_lines(image: np.ndarray, calib: Calibration,
                       offset: tuple[int, int]) -> list[SpacingResult]:
    edges = _preprocess(image)
    segs = _detect_segments(edges)
    if len(segs) < 4:
        return []

    h, w = image.shape[:2]
    diag = math.hypot(h, w)
    families = _cluster_orientations(segs)
    if not families:
        return []

    # primary axis = the family with the most distinct bars
    scored = []
    for theta_deg, fam_segs in families:
        lines = _merge_to_lines(theta_deg, fam_segs, diag)
        scored.append((len(lines), theta_deg, lines))
    scored.sort(key=lambda t: -t[0])

    results: list[SpacingResult] = []
    for rank, (n_bars, theta_deg, lines) in enumerate(scored[:2]):
        axis = "primary" if rank == 0 else "secondary"
        if n_bars < 2:
            continue

        lines.sort(key=lambda l: l["rho"])
        nx, ny = lines[0]["normal"]
        samples = []
        for a, b in zip(lines, lines[1:]):
            # Walk from a's midpoint along the family normal onto b's line, and
            # measure THAT pair through the calibration. Doing this in image
            # space and scaling afterwards would ignore perspective.
            d_px = b["rho"] - a["rho"]
            p1 = (a["mid"][0] + offset[0], a["mid"][1] + offset[1])
            p2 = (a["mid"][0] + nx * d_px + offset[0], a["mid"][1] + ny * d_px + offset[1])
            mm = calib.to_mm(p1, p2)
            if mm is not None and 1.0 < mm < 5000.0:
                samples.append(mm)

        if not samples:
            continue

        kept, stats_detail = _robust_stats(samples)
        arr = np.array(kept)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))

        results.append(SpacingResult(
            ok=True,
            axis=axis,
            median_mm=med,
            mean_mm=float(np.mean(arr)),
            mad_mm=mad,
            min_mm=float(np.min(arr)),
            max_mm=float(np.max(arr)),
            count=len(kept),
            bar_count=n_bars,
            confidence=_confidence(calib, kept, n_bars, med, mad),
            samples_mm=kept,
            detail={
                "extraction": "line",
                "axis_angle_deg": round(theta_deg, 1),
                "calibration": calib.method,
                **stats_detail,
            },
        ))

    return results


def _measure_via_lattice(image: np.ndarray, calib: Calibration,
                         offset: tuple[int, int]) -> list[SpacingResult]:
    pts = _detect_lattice_points(image)
    if len(pts) < 4:
        return []

    # Principal axes of the lattice from the shortest neighbour vectors: for a
    # regular grid these cluster tightly around the two grid directions.
    from scipy.spatial import cKDTree
    tree = cKDTree(pts)
    dists, idxs = tree.query(pts, k=min(5, len(pts)))

    vectors = []
    for i, (drow, irow) in enumerate(zip(dists, idxs)):
        for d, j in zip(drow[1:], irow[1:]):
            if d > 0:
                vectors.append(pts[j] - pts[i])
    if not vectors:
        return []
    V = np.array(vectors)
    angles = np.degrees(np.arctan2(V[:, 1], V[:, 0])) % 180.0
    hist, edges_ = np.histogram(angles, bins=36, range=(0, 180))

    axes = []
    used = np.zeros(36, dtype=bool)
    for _ in range(2):
        masked = np.where(used, 0, hist)
        if masked.max() < 2:
            break
        peak = int(np.argmax(masked))
        centre = (edges_[peak] + edges_[peak + 1]) / 2.0
        axes.append(centre)
        for b in range(36):
            c = (edges_[b] + edges_[b + 1]) / 2.0
            if abs((c - centre + 90.0) % 180.0 - 90.0) <= 20.0:
                used[b] = True

    results = []
    for rank, axis_deg in enumerate(axes[:2]):
        ax = math.radians(axis_deg)
        u = np.array([math.cos(ax), math.sin(ax)])
        samples = []
        for i, p in enumerate(pts):
            best = None
            for j in idxs[i][1:]:
                v = pts[j] - p
                n = np.linalg.norm(v)
                if n < 1e-6:
                    continue
                # only neighbours lying along this axis (within ~15°)
                if abs(float(np.dot(v / n, u))) < 0.966:
                    continue
                if best is None or n < best[0]:
                    best = (n, pts[j])
            if best is None:
                continue
            mm = calib.to_mm((p[0] + offset[0], p[1] + offset[1]),
                             (best[1][0] + offset[0], best[1][1] + offset[1]))
            if mm is not None and 1.0 < mm < 5000.0:
                samples.append(mm)

        if len(samples) < 2:
            continue
        kept, stats_detail = _robust_stats(samples)
        arr = np.array(kept)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        results.append(SpacingResult(
            ok=True,
            axis="primary" if rank == 0 else "secondary",
            median_mm=med, mean_mm=float(np.mean(arr)), mad_mm=mad,
            min_mm=float(np.min(arr)), max_mm=float(np.max(arr)),
            count=len(kept), bar_count=len(pts),
            confidence=_confidence(calib, kept, len(pts), med, mad),
            samples_mm=kept[:40],
            detail={"extraction": "lattice", "axis_angle_deg": round(axis_deg, 1),
                    "intersections_detected": len(pts),
                    "calibration": calib.method, **stats_detail},
        ))
    return results


def _confidence(calib: Calibration, samples: list[float], bar_count: int,
                median: float, mad: float) -> float:
    """Confidence = calibration quality × measurement consistency × evidence volume.

    Deliberately conservative: Agent 5 treats anything below 0.75 as UNCERTAIN
    rather than issuing a STOP WORK, so over-confidence here turns directly into
    a false stop-work order on a live site.
    """
    c = calib.confidence

    # consistency — a real grid is regular; scattered gaps mean we mis-detected
    if median > 0:
        cv = (mad * 1.4826) / median
        c *= max(0.35, 1.0 - min(cv * 3.0, 0.6))

    # evidence volume — two bars is one gap, which could be anything
    n = len(samples)
    c *= {0: 0.0, 1: 0.55, 2: 0.75, 3: 0.88}.get(n, 1.0) if n < 4 else 1.0
    if bar_count >= 6:
        c = min(c * 1.05, 0.98)

    return round(min(max(c, 0.0), 0.98), 3)


def annotate(image: np.ndarray, results: list[SpacingResult],
             calib: Calibration) -> np.ndarray:
    """Draw the measurement onto the frame — this is the evidence photo attached
    to the RFI, so it has to show what was actually measured, not just a number."""
    out = image.copy()
    h, w = out.shape[:2]

    banner = out.copy()
    cv2.rectangle(banner, (0, 0), (w, 74), (0, 0, 0), -1)
    cv2.addWeighted(banner, 0.68, out, 0.32, 0, out)
    cv2.putText(out, "FIELDPILOT AI  |  MEASUREMENT (Agent 2)", (12, 24),
                cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)
    cv2.putText(out, f"calibration: {calib.method}  (conf {calib.confidence:.2f})",
                (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 255), 1)

    y = 64
    for r in results:
        if r.median_mm is None:
            continue
        txt = (f"{r.axis}: {r.median_mm:.1f} mm  "
               f"(+/-{r.mad_mm * 1.4826:.1f}, n={r.count}, conf {r.confidence:.2f})")
        cv2.putText(out, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                    (0, 255, 180) if r.confidence >= 0.75 else (0, 190, 255), 1)
        y += 20

    if not results:
        cv2.putText(out, "no measurable spacing found", (12, 64),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 160, 255), 1)
    return out
