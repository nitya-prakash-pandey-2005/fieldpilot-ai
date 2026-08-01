#!/usr/bin/env python
"""
T2 evaluation — millimetre error against ground truth.

mAP is the wrong metric for Agent 2. What matters is: when the engine says
"190mm", how far is that from a tape measure? This script answers that and
produces the error histogram listed in docs/TRAINING_PLAN.md §10.

Two modes:

  SYNTHETIC (no data collection needed, runs anywhere)
      python models/training/eval_measurement.py --synthetic
    Builds scenes with exactly-known geometry across a range of spacings,
    viewing angles and bar diameters. Catches systematic scale errors and
    regressions. Does NOT catch lens distortion, marker flatness, motion blur,
    or real rebar's rust and shadows.

  REAL (what you quote to judges)
      python models/training/eval_measurement.py --data data/measurement_gt
    Reads a ground-truth manifest of real photographs with tape-measured
    values. Collecting ~60 photos is an afternoon's work and it is the single
    highest-credibility-per-hour task in the whole project — see §4 of the
    training plan.

Ground-truth manifest format (data/measurement_gt/ground_truth.csv):

    image,truth_mm,parameter,standoff_m,notes
    rebar_a12_1p5m_01.jpg,150,spacing,1.5,ArUco flat on deck
    rebar_a12_1p5m_02.jpg,150,spacing,1.5,marker at frame edge
    conduit_b3_2m_01.jpg,300,spacing,2.0,
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

import cv2
import numpy as np


def load_engine(rebar_weights: str | None):
    if rebar_weights:
        os.environ["REBAR_MODEL_PATH"] = rebar_weights
    from agents.measurement.estimator import MeasurementEngine
    return MeasurementEngine()


# ---------------------------------------------------------------------------

def synthetic_cases():
    sys.path.insert(0, str(REPO / "tests" / "unit"))
    from test_measurement import build_grid_scene, warp_perspective

    for spacing in (100.0, 125.0, 150.0, 175.0, 190.0, 200.0, 250.0, 300.0):
        for bar in (12.0, 16.0, 25.0):
            base = build_grid_scene(spacing_mm=spacing, bar_diameter_mm=bar)
            yield base, spacing, f"head-on d{bar:.0f}"
            for strength in (0.10, 0.18):
                yield (warp_perspective(base, strength), spacing,
                       f"persp{strength:.2f} d{bar:.0f}")


def real_cases(root: Path):
    manifest = root / "ground_truth.csv"
    if not manifest.exists():
        raise SystemExit(
            f"✖ {manifest} not found.\n"
            f"  Create it with columns: image,truth_mm,parameter,standoff_m,notes\n"
            f"  (see this script's docstring, and TRAINING_PLAN.md §4)"
        )
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = root / row["image"]
            if not path.exists():
                print(f"  ⚠ missing image, skipping: {path}")
                continue
            img = cv2.imread(str(path))
            if img is None:
                print(f"  ⚠ unreadable, skipping: {path}")
                continue
            label = row.get("notes") or f"{row.get('standoff_m', '?')}m"
            yield img, float(row["truth_mm"]), f"{row['image']} ({label})"


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--data", default=None, help="directory containing ground_truth.csv")
    ap.add_argument("--weights", default=None, help="rebar lattice model (T2 output)")
    ap.add_argument("--parameter", default="spacing")
    ap.add_argument("--out", default="models/evaluation")
    args = ap.parse_args()

    if not args.synthetic and not args.data:
        ap.error("pass --synthetic or --data <dir>")

    engine = load_engine(args.weights)
    cases = synthetic_cases() if args.synthetic else real_cases(Path(args.data))
    mode = "synthetic" if args.synthetic else "real"

    rows, errors, latencies, refusals = [], [], [], 0
    print(f"\n{'truth':>8} {'measured':>9} {'err':>8} {'err%':>6} {'conf':>5} {'calib':>10}  case")
    print("-" * 82)

    for img, truth, label in cases:
        t0 = time.time()
        out = engine.measure(img, measurement_type=args.parameter, want_annotated=False)
        ms = (time.time() - t0) * 1000
        latencies.append(ms)

        if out.get("status") != "success" or not out.get("measurements"):
            refusals += 1
            print(f"{truth:>8.1f} {'--':>9} {'--':>8} {'--':>6} {'--':>5} "
                  f"{out.get('status', '?'):>10}  {label}")
            rows.append({"truth_mm": truth, "measured_mm": None, "case": label,
                         "status": out.get("status")})
            continue

        m = out["measurements"][0]
        measured = float(m["value"])
        err = measured - truth
        errors.append(abs(err))
        calib = out.get("calibration", {}).get("method", "?")
        print(f"{truth:>8.1f} {measured:>9.1f} {err:>+8.1f} {abs(err) / truth * 100:>5.1f}% "
              f"{m.get('confidence', 0):>5.2f} {calib:>10}  {label}")
        rows.append({"truth_mm": truth, "measured_mm": measured, "error_mm": err,
                     "confidence": m.get("confidence"), "calibration": calib,
                     "gaps": m.get("gaps_measured"), "case": label, "latency_ms": ms})

    if not errors:
        raise SystemExit("\n✖ no successful measurements — nothing to evaluate.")

    # Agent 5 treats confidence < 0.75 as UNCERTAIN and does NOT issue a
    # STOP WORK on it, so accuracy has to be scored on two populations:
    #   ACTIONABLE  — what the system actually acts on. These are the numbers
    #                 that can cause a wrong decision, so the targets apply here.
    #   ALL         — reported alongside, because a system that hits the target
    #                 only by declaring everything uncertain is not accurate,
    #                 it is silent. The uncertain rate below keeps that honest.
    ACTION_THRESHOLD = 0.75

    def stats(vals: list[float]) -> dict:
        v = sorted(vals)
        return {
            "n": len(v),
            "mean_abs_error_mm": round(statistics.mean(v), 3),
            "median_abs_error_mm": round(statistics.median(v), 3),
            "p95_abs_error_mm": round(v[int(len(v) * 0.95) - 1] if len(v) >= 20 else max(v), 3),
            "max_abs_error_mm": round(max(v), 3),
        }

    actionable = [abs(r["error_mm"]) for r in rows
                  if r.get("error_mm") is not None
                  and (r.get("confidence") or 0) >= ACTION_THRESHOLD]

    all_stats = stats(errors)
    act_stats = stats(actionable) if actionable else None

    total = len(errors) + refusals
    detection_rate = len(errors) / total
    uncertain_rate = (len(errors) - len(actionable)) / total
    actionable_rate = len(actionable) / total

    summary = {
        "mode": mode,
        "timestamp": datetime.now().isoformat(),
        "weights": args.weights,
        "parameter": args.parameter,
        "action_threshold": ACTION_THRESHOLD,
        "n_cases": total,
        "refusals": refusals,
        "detection_rate": round(detection_rate, 4),
        "uncertain_rate": round(uncertain_rate, 4),
        "actionable_rate": round(actionable_rate, 4),
        "all_measurements": all_stats,
        "actionable_only": act_stats,
        "mean_latency_ms": round(statistics.mean(latencies), 1),
    }

    print("\n" + "=" * 72)
    print(f"  mode {mode}   cases {total}   refused {refusals}   "
          f"latency {statistics.mean(latencies):.0f} ms")
    print("-" * 72)
    print(f"  {'':<22}{'n':>5}{'mean':>9}{'median':>9}{'p95':>9}{'max':>10}")
    print(f"  {'all measurements':<22}{all_stats['n']:>5}"
          f"{all_stats['mean_abs_error_mm']:>9.2f}{all_stats['median_abs_error_mm']:>9.2f}"
          f"{all_stats['p95_abs_error_mm']:>9.2f}{all_stats['max_abs_error_mm']:>10.2f}")
    if act_stats:
        print(f"  {f'actionable (>={ACTION_THRESHOLD})':<22}{act_stats['n']:>5}"
              f"{act_stats['mean_abs_error_mm']:>9.2f}{act_stats['median_abs_error_mm']:>9.2f}"
              f"{act_stats['p95_abs_error_mm']:>9.2f}{act_stats['max_abs_error_mm']:>10.2f}")
    print(f"\n  actionable {actionable_rate:.1%}   uncertain {uncertain_rate:.1%}   "
          f"refused {refusals / total:.1%}")
    print("=" * 72)

    # TRAINING_PLAN §4 targets, scored on the actionable population.
    # The coverage check is what stops "declare everything uncertain" from
    # passing: the engine has to be both accurate AND willing to commit.
    checks = [
        ("actionable mean abs error <= 5mm", act_stats and act_stats["mean_abs_error_mm"] <= 5.0),
        ("actionable p95 <= 12mm", act_stats and act_stats["p95_abs_error_mm"] <= 12.0),
        ("detection rate >= 90%", detection_rate >= 0.90),
        ("actionable coverage >= 70%", actionable_rate >= 0.70),
    ]
    print()
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    if act_stats and all_stats["max_abs_error_mm"] > 3 * act_stats["max_abs_error_mm"]:
        print("\n  Note: the large-error cases all fall below the confidence")
        print("  threshold, i.e. the engine knows when it is unreliable. That is")
        print("  the property that matters — a wrong number the system refuses to")
        print("  act on cannot become a false STOP WORK.")

    if mode == "synthetic" and all(bool(ok) for _, ok in checks):
        print("\n  Synthetic targets met. This does NOT substitute for the real")
        print("  tape-measure run — it cannot see lens distortion, a curled")
        print("  marker, motion blur, or rust. Do the real run before the demo.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = out_dir / f"measurement_{mode}_{stamp}.json"
    report.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2),
                      encoding="utf-8")
    print(f"\n  report -> {report}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 4.8))
        act_signed = [r["error_mm"] for r in rows
                      if r.get("error_mm") is not None
                      and (r.get("confidence") or 0) >= ACTION_THRESHOLD]
        unc_signed = [r["error_mm"] for r in rows
                      if r.get("error_mm") is not None
                      and (r.get("confidence") or 0) < ACTION_THRESHOLD]
        # Both populations on one axis: the story is that the wide tail belongs
        # entirely to the measurements the system refuses to act on.
        bins = np.histogram_bin_edges(
            [r["error_mm"] for r in rows if r.get("error_mm") is not None],
            bins=min(30, max(8, len(errors) // 3)))
        ax.hist([act_signed, unc_signed], bins=bins, stacked=True,
                color=["#33B5E5", "#FFBB33"], edgecolor="#0b3d52",
                label=[f"actionable (conf>={ACTION_THRESHOLD})", "uncertain — not acted on"])
        ax.axvline(0, color="#00C851", lw=1.5, label="ground truth")
        ax.axvline(-5, color="#FF4444", ls="--", lw=1, label="+/-5mm target")
        ax.axvline(5, color="#FF4444", ls="--", lw=1)
        ax.set_xlabel("measured - truth (mm)")
        ax.set_ylabel("cases")
        title_err = act_stats["mean_abs_error_mm"] if act_stats else all_stats["mean_abs_error_mm"]
        ax.set_title(f"Agent 2 measurement error ({mode}) — "
                     f"actionable mean abs {title_err:.2f}mm, n={len(act_signed)}")
        ax.legend(fontsize=8)
        plt.tight_layout()
        dest = out_dir / "measurement_error_hist.png"
        plt.savefig(dest, dpi=140)
        print(f"  histogram -> {dest}")
    except ImportError:
        print("  (pip install matplotlib for the error histogram)")

    return 0 if all(bool(ok) for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
