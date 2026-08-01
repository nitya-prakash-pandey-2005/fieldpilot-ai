#!/usr/bin/env python
"""
T2 — Rebar lattice detector for Agent 2's spacing measurement.

Trains a single-class detector on rebar-grid INTERSECTIONS. Box centres become
the lattice points; agents/measurement/rebar_spacing.py then converts
nearest-neighbour pixel distances into millimetres via the ArUco/reference scale.

Why intersections rather than the bars themselves: boxes drawn around parallel
bars overlap almost completely, and NMS then deletes exactly the regular
structure we need to measure. Intersections are unambiguous point targets and a
single class trains fast on very little data.

    python models/training/train_rebar_spacing.py \
        --data data/training/rebar/rebar.yaml \
        --epochs 150 --imgsz 1280 --batch 8 --name rebar_lattice_v1

Note the higher --imgsz than T1: one class, small targets, so spend the
resolution here.

If you have bar-level (not intersection-level) rebar labels — which is what most
public rebar datasets ship — pass --derive-intersections to synthesize
intersection boxes from crossing bar boxes before training. Inspect a few of the
generated labels before committing to a run; it assumes an orthogonal grid.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
EVAL_DIR = REPO / "models" / "evaluation"
WEIGHTS_DIR = REPO / "models" / "weights"


def derive_intersections(data_yaml: Path, out_dir: Path, box_frac: float = 0.035) -> Path:
    """Turn bar-level boxes into intersection points.

    Treats every box with aspect ratio > 3 as a bar, classifies it as horizontal
    or vertical, and emits a small square box at each h×v crossing. Only valid
    for roughly orthogonal grids photographed near head-on — which is the
    inspection framing we care about, but check the output.
    """
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    root = Path(cfg.get("path", data_yaml.parent))
    out_dir.mkdir(parents=True, exist_ok=True)
    n_img = n_pts = 0

    for split in ("train", "val", "test"):
        rel = cfg.get(split)
        if not rel:
            continue
        src_lbl = root / rel.replace("images", "labels")
        src_img = root / rel
        dst_lbl = out_dir / split / "labels"
        dst_img = out_dir / split / "images"
        dst_lbl.mkdir(parents=True, exist_ok=True)
        dst_img.mkdir(parents=True, exist_ok=True)

        for lbl in sorted(src_lbl.glob("*.txt")):
            horiz, vert = [], []
            for line in lbl.read_text(encoding="utf-8").splitlines():
                p = line.split()
                if len(p) < 5:
                    continue
                xc, yc, w, h = map(float, p[1:5])
                if w <= 0 or h <= 0:
                    continue
                if w / h > 3:
                    horiz.append((xc, yc, w, h))
                elif h / w > 3:
                    vert.append((xc, yc, w, h))

            pts = []
            for _, hy, hw, _ in horiz:
                for vx, _, _, vh in vert:
                    pts.append((vx, hy))          # crossing of a h-bar and a v-bar
            if not pts:
                continue

            img = next((p for p in src_img.glob(f"{lbl.stem}.*")), None)
            if img is None:
                continue
            (dst_lbl / lbl.name).write_text(
                "".join(f"0 {x:.6f} {y:.6f} {box_frac:.6f} {box_frac:.6f}\n" for x, y in pts),
                encoding="utf-8")
            dst = dst_img / img.name
            if not dst.exists():
                try:
                    import os
                    os.link(img, dst)
                except OSError:
                    shutil.copy2(img, dst)
            n_img += 1
            n_pts += len(pts)

    new_yaml = out_dir / "rebar_lattice.yaml"
    new_yaml.write_text(yaml.safe_dump({
        "path": str(out_dir.resolve()),
        "train": "train/images", "val": "val/images", "test": "test/images",
        "nc": 1, "names": {0: "rebar_intersection"},
    }, sort_keys=False), encoding="utf-8")
    print(f"  derived {n_pts:,} intersections across {n_img:,} images -> {new_yaml}")
    if n_img == 0:
        raise SystemExit("✖ no intersections derived — your labels are probably not bar-level. "
                         "Inspect a label file and drop --derive-intersections if boxes are already points.")
    return new_yaml


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/training/rebar/rebar.yaml")
    ap.add_argument("--model", default="yolo11s.pt")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--device", default=None)
    ap.add_argument("--name", default="rebar_lattice_v1")
    ap.add_argument("--project", default="runs/fieldpilot")
    ap.add_argument("--derive-intersections", action="store_true")
    ap.add_argument("--resume", default=None)
    args = ap.parse_args()

    from ultralytics import YOLO
    import torch

    data_yaml = Path(args.data)
    if not data_yaml.exists():
        raise SystemExit(f"✖ {data_yaml} not found. Run prepare_datasets.py with --datasets D5 first.")

    if args.derive_intersections:
        data_yaml = derive_intersections(data_yaml, Path("data/training/rebar_lattice"))

    if not torch.cuda.is_available() and args.device != "cpu":
        raise SystemExit("⚠ CUDA not available — train on the GPU box, or pass --device cpu.")

    model = YOLO(args.resume or args.model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        device=args.device, project=args.project, name=args.name,
        resume=bool(args.resume),
        patience=30, cos_lr=True, optimizer="AdamW", lr0=0.001,
        # Small dense targets: mosaic helps a lot, rotation hurts (the grid
        # geometry we're about to measure must stay axis-consistent).
        mosaic=1.0, close_mosaic=20,
        degrees=5.0, scale=0.4, translate=0.1,
        fliplr=0.5, flipud=0.5,      # a rebar grid is symmetric both ways
        hsv_v=0.5, erasing=0.25,     # partial occlusion by formwork/workers
        plots=True,
    )

    metrics = model.val(data=str(data_yaml), split="test", imgsz=args.imgsz)
    run_dir = Path(args.project) / args.name
    report = {
        "run": args.name,
        "timestamp": datetime.now().isoformat(),
        "task": "rebar_lattice_detection",
        "mAP50": round(float(metrics.box.map50), 4),
        "mAP50_95": round(float(metrics.box.map), 4),
        "precision": round(float(metrics.box.mp), 4),
        "recall": round(float(metrics.box.mr), 4),
        "note": ("mAP is a proxy here. The metric that matters is millimetre error — "
                 "run models/training/eval_measurement.py against tape-measure ground truth."),
    }
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / f"rebar_{args.name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    best = run_dir / "weights" / "best.pt"
    if best.exists():
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = WEIGHTS_DIR / f"{args.name}.pt"
        shutil.copy2(best, dest)
        print(f"\n  weights -> {dest}")
        print(f"  set in .env:  REBAR_MODEL_PATH={dest.relative_to(REPO).as_posix()}")

    print(f"  mAP50 {report['mAP50']:.4f}  recall {report['recall']:.4f}")
    print("\n  next — the metric that actually matters:")
    print(f"    python models/training/eval_measurement.py --weights {best}")


if __name__ == "__main__":
    main()
