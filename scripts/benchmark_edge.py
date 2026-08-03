#!/usr/bin/env python
"""
Edge inference benchmark — is the quantized model actually usable?

Quantizing to INT8 is only worth it if the accuracy cost is small, and "small"
has to be measured. A 3.5x smaller model that misses a fallen worker is not a
win. This compares INT8 against FP32 on three axes:

  SIZE      trivially measurable, and what fits in a phone app bundle
  LATENCY   p50/p95 per frame, which sets the achievable duty cycle
  AGREEMENT do the two models find the SAME people in the same places?

Agreement is the one that matters and the one usually skipped. Reporting only
"INT8 is 2x faster" says nothing about whether it still works. Here it is
measured as detection-count match plus mean IoU of matched boxes — if INT8
finds the same workers with boxes that overlap the FP32 boxes closely, the
quantization is safe for this use.

    python scripts/benchmark_edge.py
    python scripts/benchmark_edge.py --frames 100 --source data/sample_construction.mp4
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

from agents.edge.runtime import EdgeDetector


def load_frames(source: str | None, count: int) -> list[np.ndarray]:
    """Real frames, not synthetic noise — quantization error depends on the
    activation distribution, so random pixels would give a meaningless answer."""
    import cv2

    candidates = [source] if source else [
        str(REPO / "data" / "sample_construction.mp4"),
        str(REPO / "data" / "sample_construction_output.mp4"),
    ]
    for path in candidates:
        if not path or not Path(path).exists():
            continue
        cap = cv2.VideoCapture(path)
        frames = []
        # Spread the sample across the clip rather than taking the first N,
        # which would all be near-identical and flatter both models equally.
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or count
        step = max(1, total // max(count, 1))
        idx = 0
        while len(frames) < count:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                frames.append(frame)
            idx += 1
        cap.release()
        if frames:
            print(f"  loaded {len(frames)} frames from {Path(path).name}")
            return frames

    for img in (REPO / "data" / "demo_images").glob("*.png"):
        frame = cv2.imread(str(img))
        if frame is not None:
            print(f"  no video found — using {img.name} repeated")
            return [frame] * count
    raise SystemExit("✖ no sample media found under data/")


def diagnose_quantization(path: Path) -> dict:
    """Identify HOW a model was quantized, because it decides whether INT8 is
    faster or slower.

    Two schemes produce very different runtime behaviour:

      DYNAMIC  (quantize_dynamic)  -> DynamicQuantizeLinear + ConvInteger
        Activation scales are computed at inference time, every frame, for every
        tensor. ConvInteger emits int32 and needs separate Cast/Mul/Add nodes to
        rescale, so the graph roughly doubles in size. On a CPU this is routinely
        SLOWER than FP32 despite the smaller file, and mobile NPU delegates
        (NNAPI, QNN) generally cannot consume it either — they fall back to CPU.

      STATIC   (quantize_static, needs a calibration set) -> QLinearConv / QDQ
        Scales are precomputed and folded in, and the conv is a single fused
        int8 kernel. This is the form that actually runs fast, and the form the
        NPU delegates accept.

    A small file is not the goal. A fast, NPU-consumable file is.
    """
    try:
        import collections
        import onnx
    except ImportError:
        return {"available": False}

    try:
        model = onnx.load(str(path))
    except Exception as e:
        return {"available": False, "error": str(e)}

    ops = collections.Counter(n.op_type for n in model.graph.node)
    dynamic = ops.get("DynamicQuantizeLinear", 0)
    conv_integer = ops.get("ConvInteger", 0)
    qlinear = ops.get("QLinearConv", 0)
    qdq = ops.get("QuantizeLinear", 0) + ops.get("DequantizeLinear", 0)

    if dynamic or conv_integer:
        scheme = "dynamic"
    elif qlinear or qdq:
        scheme = "static"
    elif ops.get("Conv", 0):
        scheme = "float"
    else:
        scheme = "unknown"

    return {
        "available": True,
        "scheme": scheme,
        "total_nodes": len(model.graph.node),
        "DynamicQuantizeLinear": dynamic,
        "ConvInteger": conv_integer,
        "QLinearConv": qlinear,
        "QuantizeLinear+DequantizeLinear": qdq,
        "float_Conv": ops.get("Conv", 0),
    }


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def bench(detector: EdgeDetector, frames: list[np.ndarray], warmup: int = 3):
    """Latency plus the detections themselves, for the agreement comparison."""
    for f in frames[:warmup]:
        detector.detect(f)                      # first calls include lazy init

    lat, infer, per_frame = [], [], []
    for f in frames:
        r = detector.detect(f)
        lat.append(r.total_ms)
        infer.append(r.inference_ms)
        per_frame.append([(d.bbox, d.confidence) for d in r.detections])
    return lat, infer, per_frame


def summarise(name: str, lat: list[float], infer: list[float], size_mb: float,
              provider: str) -> dict:
    lat_sorted = sorted(lat)
    return {
        "model": name,
        "size_mb": size_mb,
        "provider": provider,
        "total_p50_ms": round(statistics.median(lat), 2),
        "total_p95_ms": round(lat_sorted[int(len(lat_sorted) * 0.95) - 1], 2),
        "inference_p50_ms": round(statistics.median(infer), 2),
        "fps_ceiling": round(1000.0 / statistics.median(lat), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--source", default=None)
    ap.add_argument("--int8", default="models/weights/yolo11n-pose-int8.onnx")
    ap.add_argument("--fp32", default="models/weights/yolo11n-pose.onnx")
    ap.add_argument("--out", default="models/evaluation")
    args = ap.parse_args()

    print("\nLoading sample frames…")
    frames = load_frames(args.source, args.frames)

    results, detections = {}, {}
    for label, path in (("fp32", args.fp32), ("int8", args.int8)):
        p = REPO / path if not Path(path).is_absolute() else Path(path)
        if not p.exists():
            print(f"  ⚠ {label}: {p} not found — skipping")
            continue
        print(f"\nBenchmarking {label}: {p.name}")
        det = EdgeDetector(model_path=str(p))
        if not det.ready:
            print(f"  ✖ could not load: {det.load_error}")
            continue
        lat, infer, per_frame = bench(det, frames)
        results[label] = summarise(label, lat, infer, round(p.stat().st_size / 1e6, 2),
                                   det.provider)
        results[label]["quantization"] = diagnose_quantization(p)
        detections[label] = per_frame
        q = results[label]["quantization"]
        print(f"  provider {det.provider}  p50 {results[label]['total_p50_ms']}ms  "
              f"({results[label]['fps_ceiling']} fps ceiling)")
        if q.get("available"):
            print(f"  quantization: {q['scheme']}  ({q['total_nodes']} nodes, "
                  f"ConvInteger={q['ConvInteger']}, QLinearConv={q['QLinearConv']})")

    if not results:
        raise SystemExit("✖ no models could be benchmarked")

    print("\n" + "=" * 78)
    print(f"  {'model':<8}{'size MB':>9}{'p50 ms':>9}{'p95 ms':>9}{'infer ms':>10}{'fps':>7}  provider")
    for k, r in results.items():
        print(f"  {k:<8}{r['size_mb']:>9.2f}{r['total_p50_ms']:>9.2f}{r['total_p95_ms']:>9.2f}"
              f"{r['inference_p50_ms']:>10.2f}{r['fps_ceiling']:>7.1f}  {r['provider']}")
    print("=" * 78)

    comparison = {}
    if "fp32" in results and "int8" in results:
        comparison["size_reduction_x"] = round(results["fp32"]["size_mb"] / results["int8"]["size_mb"], 2)
        comparison["speedup_x"] = round(results["fp32"]["total_p50_ms"] / results["int8"]["total_p50_ms"], 2)

        # --- agreement -----------------------------------------------------
        matched_iou, count_match, total_fp32, total_int8, missed = [], 0, 0, 0, 0
        for a, b in zip(detections["fp32"], detections["int8"]):
            total_fp32 += len(a)
            total_int8 += len(b)
            if len(a) == len(b):
                count_match += 1
            used = set()
            for box_a, _ in a:
                best, best_j = 0.0, None
                for j, (box_b, _) in enumerate(b):
                    if j in used:
                        continue
                    v = iou(box_a, box_b)
                    if v > best:
                        best, best_j = v, j
                if best_j is not None and best > 0.5:
                    used.add(best_j)
                    matched_iou.append(best)
                else:
                    missed += 1

        n = len(detections["fp32"])
        comparison["detection_count_agreement"] = round(count_match / n, 3) if n else None
        comparison["fp32_detections"] = total_fp32
        comparison["int8_detections"] = total_int8
        comparison["mean_iou_of_matched"] = round(statistics.mean(matched_iou), 4) if matched_iou else None
        comparison["fp32_boxes_int8_missed"] = missed
        comparison["miss_rate"] = round(missed / total_fp32, 4) if total_fp32 else None

        print(f"\n  size reduction      {comparison['size_reduction_x']}x")
        print(f"  speedup             {comparison['speedup_x']}x")
        print(f"  frames with same detection count   {comparison['detection_count_agreement']:.1%}")
        print(f"  detections  fp32 {total_fp32}  int8 {total_int8}")
        print(f"  mean IoU of matched boxes          {comparison['mean_iou_of_matched']}")
        print(f"  fp32 boxes INT8 missed             {missed} ({comparison['miss_rate']:.1%})")

        accuracy_ok = ((comparison["mean_iou_of_matched"] or 0) >= 0.85
                       and (comparison["miss_rate"] or 1) <= 0.05)
        if (comparison["mean_iou_of_matched"] or 0) < 0.85:
            print("\n  ⚠ matched boxes disagree noticeably — check the calibration set")
        if (comparison["miss_rate"] or 0) > 0.05:
            print("  ⚠ INT8 misses >5% of FP32 detections — NOT safe for safety-critical use")
        if accuracy_ok:
            print("\n  ✔ ACCURACY: INT8 agrees with FP32 closely enough for on-device "
                  "safety screening.")

        # Speed is a separate verdict from accuracy, and the interesting failure
        # is a model that is accurate but slower than the float model it replaced.
        q = results["int8"].get("quantization", {})
        if comparison["speedup_x"] < 1.0:
            comparison["speed_regression"] = True
            comparison["diagnosis"] = q.get("scheme")
            print(f"\n  ✖ SPEED: INT8 is {1 / comparison['speedup_x']:.1f}x SLOWER than FP32, "
                  f"not faster.")
            if q.get("scheme") == "dynamic":
                print("     Cause: this model is DYNAMICALLY quantized —")
                print(f"       DynamicQuantizeLinear x{q.get('DynamicQuantizeLinear')}  "
                      f"(activation scales recomputed every single inference)")
                print(f"       ConvInteger x{q.get('ConvInteger')}  "
                      f"(unfused int8 conv: int32 out, then Cast/Mul/Add to rescale)")
                print(f"       QLinearConv x{q.get('QLinearConv')}  "
                      f"(the FUSED fast kernel — absent)")
                print(f"       node count {results['fp32']['quantization'].get('total_nodes')}"
                      f" -> {q.get('total_nodes')}")
                print("     Fix: re-export with STATIC quantization and a calibration set.")
                print("       python models/training/export_edge.py \\")
                print("         --weights <model.pt> --formats int8 \\")
                print("         --data data/training/fieldpilot28/fieldpilot28.yaml")
                print("     This matters for the phone too, not just this CPU: NNAPI and")
                print("     QNN delegates generally cannot consume ConvInteger graphs and")
                print("     silently fall back to CPU — so a dynamically quantized model")
                print("     gets no NPU acceleration at all.")
            else:
                print(f"     Quantization scheme detected: {q.get('scheme')}. Profile per-op "
                      f"to find the regression.")
            print("\n     Meanwhile, FP32 at "
                  f"{results['fp32']['total_p50_ms']:.0f}ms is the better on-device choice "
                  f"and still meets a 5s duty cycle with ~85x headroom.")
        else:
            comparison["speed_regression"] = False
            print(f"  ✔ SPEED: INT8 is {comparison['speedup_x']:.2f}x faster than FP32.")

    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f"edge_benchmark_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "frames": len(frames),
        "results": results,
        "comparison": comparison,
        "caveat": "Measured on the desktop CPU build of onnxruntime. Phone NPU "
                  "latency will differ substantially — re-run on the target "
                  "device via onnxruntime-react-native before quoting figures.",
    }, indent=2), encoding="utf-8")
    print(f"\n  report -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
