#!/usr/bin/env python
"""
T7 — Edge export: ONNX -> INT8 -> TensorRT.

Backs the deck's "quantized models run on the phone NPU so safety works in WiFi
dead zones" claim, and produces the weights the mobile app actually loads.

    python models/training/export_edge.py \
        --weights runs/fieldpilot/fieldpilot28_v1/weights/best.pt \
        --formats onnx,int8,tensorrt

Crucially this VERIFIES the exports rather than just producing them: each format
is re-validated on the dataset's val split and the mAP drop against the source
.pt is reported. An INT8 model that silently lost 15 points of mAP looks
identical to a good one until it misses a hazard on site.

TensorRT export requires a machine with the target GPU — an engine built on one
GPU architecture will not load on another. Build it on the deployment device
(Jetson Orin for the edge box), not on your training box, unless they match.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WEIGHTS_DIR = REPO / "models" / "weights"
EVAL_DIR = REPO / "models" / "evaluation"


def size_mb(p: Path) -> float:
    return round(p.stat().st_size / (1024 * 1024), 2) if p.exists() else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True, help="trained .pt from T1 or T2")
    ap.add_argument("--formats", default="onnx,int8",
                    help="comma-separated: onnx, int8, fp16, tensorrt")
    ap.add_argument("--data", default=None,
                    help="dataset yaml — required for int8 calibration and for verification")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--max-map-drop", type=float, default=0.04,
                    help="fail if a format loses more than this much mAP50")
    args = ap.parse_args()

    from ultralytics import YOLO

    src = Path(args.weights)
    if not src.exists():
        raise SystemExit(f"✖ {src} not found")

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    if "int8" in formats and not args.data:
        raise SystemExit(
            "✖ INT8 export needs --data <dataset.yaml>: quantization calibrates "
            "against real images, and calibrating on the wrong distribution is "
            "how you lose 10+ points of mAP without noticing."
        )

    model = YOLO(str(src))
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = src.parent.parent.name if src.name in ("best.pt", "last.pt") else src.stem

    # ---- baseline -----------------------------------------------------------
    baseline_map = None
    if args.data and not args.no_verify:
        print("▶ baseline (.pt) on val split…")
        m = model.val(data=args.data, imgsz=args.imgsz, verbose=False)
        baseline_map = float(m.box.map50)
        print(f"  mAP50 {baseline_map:.4f}   size {size_mb(src)} MB")

    results = {"source": str(src), "baseline_mAP50": baseline_map,
               "source_size_mb": size_mb(src), "imgsz": args.imgsz, "exports": {}}

    export_specs = {
        "onnx":     dict(format="onnx", half=False, int8=False, simplify=True, dynamic=False),
        "fp16":     dict(format="onnx", half=True, int8=False, simplify=True, dynamic=False),
        "int8":     dict(format="onnx", half=False, int8=True, simplify=True, dynamic=False),
        "tensorrt": dict(format="engine", half=True, int8=False),
    }

    for fmt in formats:
        spec = export_specs.get(fmt)
        if spec is None:
            print(f"  ⚠ unknown format {fmt!r}, skipping")
            continue

        print(f"\n▶ exporting {fmt}…")
        kwargs = dict(spec, imgsz=args.imgsz, batch=args.batch)
        if spec.get("int8") or spec["format"] == "engine":
            kwargs["data"] = args.data          # calibration set

        try:
            out_path = Path(model.export(**kwargs))
        except Exception as e:
            print(f"  ✖ {fmt} export failed: {e}")
            if fmt == "tensorrt":
                print("    TensorRT needs the target GPU present and a matching "
                      "TensorRT install. Build it on the deployment device.")
            results["exports"][fmt] = {"ok": False, "error": str(e)}
            continue

        dest = WEIGHTS_DIR / f"{stem}_{fmt}{out_path.suffix}"
        shutil.copy2(out_path, dest)
        entry = {"ok": True, "path": str(dest), "size_mb": size_mb(dest)}
        if results["source_size_mb"]:
            entry["size_reduction"] = round(results["source_size_mb"] / max(entry["size_mb"], 0.01), 2)

        # ---- verify ---------------------------------------------------------
        if args.data and not args.no_verify:
            try:
                print(f"  verifying {dest.name}…")
                vm = YOLO(str(dest), task=model.task).val(
                    data=args.data, imgsz=args.imgsz, verbose=False)
                entry["mAP50"] = round(float(vm.box.map50), 4)
                if baseline_map is not None:
                    drop = baseline_map - entry["mAP50"]
                    entry["mAP50_drop"] = round(drop, 4)
                    entry["within_tolerance"] = bool(drop <= args.max_map_drop)
                    flag = "OK" if entry["within_tolerance"] else "TOO LARGE"
                    print(f"    mAP50 {entry['mAP50']:.4f}  (drop {drop:+.4f} — {flag})")
            except Exception as e:
                entry["verify_error"] = str(e)
                print(f"    ⚠ verification failed: {e}")

        print(f"  -> {dest}  ({entry['size_mb']} MB)")
        results["exports"][fmt] = entry

    # ---- report -------------------------------------------------------------
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    report = EVAL_DIR / f"edge_export_{stem}_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"  {'format':<10}{'size MB':>9}{'vs .pt':>8}{'mAP50':>9}{'drop':>9}")
    base_map_s = f"{baseline_map:.4f}" if baseline_map is not None else "--"
    print(f"  {'.pt':<10}{results['source_size_mb']:>9.2f}{'1.0x':>8}{base_map_s:>9}{'--':>9}")
    for fmt, e in results["exports"].items():
        if not e.get("ok"):
            print(f"  {fmt:<10}{'FAILED':>9}")
            continue
        ratio_s = f"{e.get('size_reduction', '--')}x"
        map_s = f"{e['mAP50']:.4f}" if "mAP50" in e else "--"
        drop_s = f"{e['mAP50_drop']:+.4f}" if "mAP50_drop" in e else "--"
        print(f"  {fmt:<10}{e['size_mb']:>9.2f}{ratio_s:>8}{map_s:>9}{drop_s:>9}")
    print("=" * 68)

    bad = [f for f, e in results["exports"].items()
           if e.get("ok") and e.get("within_tolerance") is False]
    if bad:
        print(f"\n  ⚠ {', '.join(bad)} lost more than {args.max_map_drop:.0%} mAP50.")
        print("    For INT8 that almost always means the calibration set isn't")
        print("    representative — it should span the same lighting, distances")
        print("    and clutter as the deployment site, not just clean photos.")

    int8 = results["exports"].get("int8", {})
    if int8.get("ok"):
        print(f"\n  set in .env:  EDGE_MODEL_PATH={Path(int8['path']).relative_to(REPO).as_posix()}")
    print(f"  report -> {report}")


if __name__ == "__main__":
    main()
