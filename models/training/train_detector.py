#!/usr/bin/env python
"""
T1 — Construction detector fine-tune (FieldPilot-28).

Fine-tunes YOLO11-seg (or RT-DETR, for the comparison run) on the harmonized
dataset produced by prepare_datasets.py, then evaluates per-taxonomy-group mAP
and writes the evaluation artefacts listed in docs/TRAINING_PLAN.md §10.

    python models/training/train_detector.py \
        --data data/training/fieldpilot28/fieldpilot28.yaml \
        --model yolo11m-seg.pt --epochs 120 --imgsz 960 --batch 16 \
        --name fieldpilot28_v1

Resume an interrupted run (Colab/Kaggle session limits):
    python models/training/train_detector.py --resume runs/detect/fieldpilot28_v1/weights/last.pt

Hyperparameter rationale lives in docs/TRAINING_PLAN.md §3 — read it before
changing imgsz, which is the single biggest lever for thin structures like
rebar and conduit.
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


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", default="data/training/fieldpilot28/fieldpilot28.yaml")
    p.add_argument("--model", default="yolo11m-seg.pt",
                   help="yolo11{n,s,m,l}-seg.pt, or rtdetr-l.pt for the §3.4 comparison run")
    p.add_argument("--epochs", type=int, default=120)
    p.add_argument("--imgsz", type=int, default=960)
    p.add_argument("--batch", type=int, default=16, help="-1 for Ultralytics auto-batch")
    p.add_argument("--device", default=None, help="'0', '0,1', or 'cpu'. Default: auto")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--name", default=None)
    p.add_argument("--project", default="runs/fieldpilot")
    p.add_argument("--resume", default=None, help="path to last.pt")
    p.add_argument("--patience", type=int, default=25)
    p.add_argument("--no-deploy", action="store_true",
                   help="skip copying best.pt into models/weights/")
    return p.parse_args()


def preflight(data_yaml: Path) -> dict:
    """Fail before burning 16 GPU-hours on a dataset that isn't there."""
    if not data_yaml.exists():
        raise SystemExit(
            f"✖ {data_yaml} not found.\n"
            f"  Run: python models/training/prepare_datasets.py --out data/training"
        )
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    root = Path(cfg.get("path", data_yaml.parent))
    counts = {}
    for split in ("train", "val", "test"):
        rel = cfg.get(split)
        if not rel:
            continue
        d = root / rel
        counts[split] = sum(1 for _ in d.glob("*")) if d.exists() else 0
    if counts.get("train", 0) < 100:
        raise SystemExit(
            f"✖ only {counts.get('train', 0)} training images found under {root}.\n"
            f"  prepare_datasets.py probably skipped every source — check its output "
            f"for 'SKIPPED' lines (missing ROBOFLOW_API_KEY or --dN-root)."
        )
    print(f"  dataset: {counts}  |  {cfg.get('nc')} classes")
    return cfg


def group_metrics(metrics, class_ids: list[int], taxonomy: dict) -> dict:
    """Per-group mAP. Ultralytics gives per-class AP arrays in
    metrics.box.ap50 / .ap, indexed by position in metrics.box.ap_class_index —
    NOT by class id, so the indirection below is required."""
    try:
        idx_of = {int(c): i for i, c in enumerate(metrics.box.ap_class_index)}
        ap50 = metrics.box.ap50
        ap = metrics.box.ap
    except AttributeError:
        return {}

    out = {}
    for group, ids in taxonomy.get("groups", {}).items():
        present = [idx_of[c] for c in ids if c in idx_of]
        if not present:
            out[group] = {"mAP50": None, "mAP50_95": None, "classes_present": 0}
            continue
        out[group] = {
            "mAP50": round(float(sum(ap50[i] for i in present) / len(present)), 4),
            "mAP50_95": round(float(sum(ap[i] for i in present) / len(present)), 4),
            "classes_present": len(present),
        }
    return out


def main():
    args = parse_args()
    from ultralytics import YOLO, RTDETR
    import torch

    data_yaml = Path(args.data)
    cfg = preflight(data_yaml)
    taxonomy = yaml.safe_load((HERE / "taxonomy.yaml").read_text(encoding="utf-8"))

    name = args.name or f"fieldpilot28_{datetime.now():%Y%m%d_%H%M}"
    is_rtdetr = "rtdetr" in args.model.lower()
    Loader = RTDETR if is_rtdetr else YOLO

    if not torch.cuda.is_available() and args.device != "cpu":
        print("⚠ CUDA not available. This will take days on CPU.")
        print("  Train on the GPU box (docs/TRAINING_PLAN.md §1), or pass --device cpu to proceed anyway.")
        raise SystemExit(1)

    model = Loader(args.resume or args.model)

    # Augmentation profile tuned for construction sites, not COCO.
    # Rationale per-setting: docs/TRAINING_PLAN.md §3.
    train_kwargs = dict(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=args.project,
        name=name,
        patience=args.patience,
        resume=bool(args.resume),
        cos_lr=True,
        optimizer="AdamW",
        lr0=0.001,
        warmup_epochs=3,
        # -- augmentation --
        mosaic=1.0,
        close_mosaic=15,     # last 15 epochs run clean, for calibration
        copy_paste=0.3,      # boosts the sparse PPE-negative classes
        degrees=10.0,        # glasses footage tilts; site photos rarely rotate more
        translate=0.1,
        scale=0.5,
        fliplr=0.5,
        flipud=0.0,          # construction scenes are never upside down
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.5,           # blazing sun -> dark basement
        erasing=0.2,         # occlusion robustness (workers behind formwork)
        plots=True,
        val=True,
    )
    if is_rtdetr:
        # RT-DETR's Ultralytics head rejects several YOLO-only augmentation keys.
        for k in ("copy_paste", "close_mosaic", "erasing"):
            train_kwargs.pop(k, None)

    print(f"\n▶ training {args.model} → {args.project}/{name}")
    print(f"  imgsz={args.imgsz} batch={args.batch} epochs={args.epochs}")
    model.train(**train_kwargs)

    # ---- evaluation on the held-out TEST split (not val, which drove early stopping)
    print("\n▶ evaluating on test split…")
    metrics = model.val(data=str(data_yaml), split="test", imgsz=args.imgsz, plots=True)

    run_dir = Path(args.project) / name
    names = cfg.get("names", {})
    per_class = {}
    try:
        for i, c in enumerate(metrics.box.ap_class_index):
            per_class[names.get(int(c), str(c))] = {
                "mAP50": round(float(metrics.box.ap50[i]), 4),
                "mAP50_95": round(float(metrics.box.ap[i]), 4),
                "precision": round(float(metrics.box.p[i]), 4),
                "recall": round(float(metrics.box.r[i]), 4),
            }
    except (AttributeError, IndexError):
        pass

    report = {
        "run": name,
        "timestamp": datetime.now().isoformat(),
        "base_model": args.model,
        "imgsz": args.imgsz,
        "epochs": args.epochs,
        "dataset": str(data_yaml),
        "overall": {
            "mAP50": round(float(metrics.box.map50), 4),
            "mAP50_95": round(float(metrics.box.map), 4),
            "precision": round(float(metrics.box.mp), 4),
            "recall": round(float(metrics.box.mr), 4),
        },
        "by_group": group_metrics(metrics, list(names), taxonomy),
        "by_class": per_class,
        "weights": str(run_dir / "weights" / "best.pt"),
    }

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    report_path = EVAL_DIR / f"detector_{name}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Ultralytics writes these into the run dir; copy to models/evaluation for §10.
    for src_name, dst_name in (("confusion_matrix_normalized.png", "detector_confusion_matrix.png"),
                               ("BoxPR_curve.png", "detector_pr_curve.png"),
                               ("PR_curve.png", "detector_pr_curve.png")):
        src = run_dir / src_name
        if src.exists():
            shutil.copy2(src, EVAL_DIR / dst_name)

    print("\n" + "=" * 62)
    print(f"  overall  mAP50 {report['overall']['mAP50']:.4f}   "
          f"mAP50-95 {report['overall']['mAP50_95']:.4f}")
    for group, m in report["by_group"].items():
        if m.get("mAP50") is not None:
            print(f"  {group:<11} mAP50 {m['mAP50']:.4f}   ({m['classes_present']} classes)")
    print("=" * 62)

    # Compare against the targets in TRAINING_PLAN §3 so you know immediately
    # whether this run is shippable or whether it's a mapping bug.
    targets = {"overall": 0.72, "ppe": 0.85, "equipment": 0.80, "structural": 0.55}
    shortfalls = []
    if report["overall"]["mAP50"] < targets["overall"]:
        shortfalls.append(f"overall {report['overall']['mAP50']:.3f} < {targets['overall']}")
    for g, t in targets.items():
        if g == "overall":
            continue
        v = report["by_group"].get(g, {}).get("mAP50")
        if v is not None and v < t:
            shortfalls.append(f"{g} {v:.3f} < {t}")
    if shortfalls:
        print("\n⚠ below the TRAINING_PLAN §3 minimums: " + "; ".join(shortfalls))
        print("  Check models/evaluation/class_histogram.png first — a starved or")
        print("  mis-merged class is a far more common cause than under-training.")
    else:
        print("\n✔ all TRAINING_PLAN §3 minimums met.")

    if not args.no_deploy:
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        best = run_dir / "weights" / "best.pt"
        if best.exists():
            dest = WEIGHTS_DIR / f"{name}.pt"
            shutil.copy2(best, dest)
            print(f"\n  weights -> {dest}")
            print(f"  set in .env:  YOLO_MODEL_PATH={dest.relative_to(REPO).as_posix()}")

    print(f"  report  -> {report_path}")
    print(f"\n  next: python models/training/export_edge.py --weights {run_dir / 'weights' / 'best.pt'}")


if __name__ == "__main__":
    main()
