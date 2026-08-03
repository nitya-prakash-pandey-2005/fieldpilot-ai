#!/usr/bin/env python
"""
Static INT8 quantization for the edge model — the fix for a slow "optimised" model.

Background, because this is the whole reason the script exists. The repo's
existing yolo11n-pose-int8.onnx was produced by DYNAMIC quantization. Measured
against FP32 on the same frames (scripts/benchmark_edge.py):

    accuracy   mean IoU 0.971, 0 missed detections   — excellent
    size       11.8 MB -> 3.4 MB (3.46x)             — as advertised
    speed      73 ms -> 1250 ms (16.7x SLOWER)       — the opposite of the point

The cause is visible in the graph: 86 DynamicQuantizeLinear nodes recomputing
activation scales on every single inference, and 97 ConvInteger ops, which emit
int32 and need separate Cast/Mul/Add nodes to rescale. Node count goes 405 ->
974. There are zero QLinearConv ops — the fused int8 kernel that makes INT8 fast.

Static quantization fixes this by measuring activation ranges ONCE, offline,
against representative frames (calibration), then folding those scales into the
graph. The result uses QDQ or QOperator form, which:

  - has no per-inference scale computation
  - fuses into single int8 conv kernels
  - is the form NNAPI / QNN / CoreML delegates can actually consume. A
    ConvInteger graph typically falls back to CPU on a phone, so a dynamically
    quantized model gets NO NPU acceleration at all — which matters more for
    this project than the desktop numbers.

CALIBRATION DATA MATTERS. The scales come from whatever frames you feed here, so
they must look like deployment: same lighting range, same distances, same
clutter. Calibrating on clean stock photos and deploying to a dim basement is
how INT8 quietly loses accuracy.

    python models/training/quantize_static.py \
        --model models/weights/yolo11n-pose.onnx \
        --calib-video data/sample_construction.mp4 \
        --out models/weights/yolo11n-pose-int8-static.onnx

    # then confirm it is actually better
    python scripts/benchmark_edge.py --int8 models/weights/yolo11n-pose-int8-static.onnx
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

import numpy as np


class FrameCalibrationReader:
    """Feeds real frames to the quantizer, preprocessed exactly as at inference.

    Using the same preprocess() as the runtime is not a nicety: if calibration
    sees a different normalisation or channel order than inference, the measured
    activation ranges are wrong and the quantized model loses accuracy for
    reasons that are very hard to trace back to here.
    """

    def __init__(self, frames: list[np.ndarray], input_name: str, size: int):
        from agents.edge.runtime import preprocess

        self.input_name = input_name
        self._tensors = []
        for f in frames:
            tensor, _, _, _ = preprocess(f, size)
            self._tensors.append(tensor)
        self._iter = None

    def get_next(self):
        if self._iter is None:
            self._iter = iter(self._tensors)
        batch = next(self._iter, None)
        return None if batch is None else {self.input_name: batch}

    def rewind(self):
        self._iter = None


def find_detection_head_nodes(model_path: Path) -> tuple[list[str], str | None]:
    """Node names belonging to the detection/pose head, which must stay FP32.

    Why this is not optional: quantizing the head to uint8 produced a model that
    detected NOTHING — 0 detections against FP32's 19 on the same frames, while
    the backbone quantized perfectly. The head is where feature maps become box
    coordinates in pixels (0-640) and DFL logits, so its activations span a far
    wider range than the backbone's. Squeezing that into 256 levels destroys the
    box decode, and it fails silently: the model runs, produces well-formed
    output, and finds nothing.

    Detected structurally rather than hardcoded: walk back from the graph output
    to find the highest /model.N/ module index, which is the head in every
    Ultralytics export (model.23 for YOLO11n-pose, different for other variants),
    then exclude every node under that prefix.
    """
    import re

    import onnx

    graph = onnx.load(str(model_path)).graph
    producer: dict[str, object] = {}
    for node in graph.node:
        for out in node.output:
            producer[out] = node

    # Bounded backward walk from the output.
    seen: set[str] = set()
    frontier = [graph.output[0].name]
    module_indices: set[int] = set()
    for _ in range(16):
        nxt: list[str] = []
        for name in frontier:
            node = producer.get(name)
            if node is None or node.name in seen:
                continue
            seen.add(node.name)
            m = re.match(r"^/model\.(\d+)/", node.name or "")
            if m:
                module_indices.add(int(m.group(1)))
            nxt.extend(node.input)
        if not nxt:
            break
        frontier = nxt

    if not module_indices:
        # Unnamed or differently-named export — fall back to the nodes we walked.
        return sorted(seen), None

    head_idx = max(module_indices)
    prefix = f"/model.{head_idx}/"
    head_nodes = [n.name for n in graph.node if (n.name or "").startswith(prefix)]
    return head_nodes, prefix


def load_calibration_frames(video: Path | None, count: int) -> list[np.ndarray]:
    import cv2

    frames: list[np.ndarray] = []
    if video and video.exists():
        cap = cv2.VideoCapture(str(video))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or count
        # Spread across the clip: consecutive frames are near-identical and would
        # give the quantizer a far narrower activation range than reality.
        step = max(1, total // max(count, 1))
        i = 0
        while len(frames) < count:
            ok, frame = cap.read()
            if not ok:
                break
            if i % step == 0:
                frames.append(frame)
            i += 1
        cap.release()

    if len(frames) < count:
        for img in sorted((REPO / "data" / "demo_images").glob("*.png")):
            frame = cv2.imread(str(img))
            if frame is not None:
                frames.append(frame)
            if len(frames) >= count:
                break

    if not frames:
        raise SystemExit("✖ no calibration frames found. Pass --calib-video, or put "
                         "representative site images in data/demo_images/")
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="models/weights/yolo11n-pose.onnx",
                    help="FP32 ONNX to quantize")
    ap.add_argument("--out", default="models/weights/yolo11n-pose-int8-static.onnx")
    ap.add_argument("--calib-video", default="data/sample_construction.mp4")
    ap.add_argument("--calib-frames", type=int, default=64,
                    help="32-128 is usually plenty; more costs time, not accuracy")
    ap.add_argument("--input-size", type=int, default=640)
    ap.add_argument("--format", choices=["qdq", "qoperator"], default="qdq",
                    help="QDQ is the portable form mobile delegates prefer; "
                         "QOperator can be marginally faster on CPU")
    ap.add_argument("--per-channel", action="store_true", default=True,
                    help="per-channel weight scales — better accuracy, same speed")
    ap.add_argument("--quantize-head", action="store_true",
                    help="ALSO quantize the detection head. Measured to produce a "
                         "model that detects nothing; exposed only so the failure "
                         "is reproducible.")
    args = ap.parse_args()

    try:
        from onnxruntime.quantization import (CalibrationMethod, QuantFormat, QuantType,
                                              quantize_static)
        from onnxruntime.quantization.shape_inference import quant_pre_process
        import onnxruntime as ort
    except ImportError as e:
        raise SystemExit(f"✖ needs onnxruntime with quantization support: {e}")

    src = REPO / args.model if not Path(args.model).is_absolute() else Path(args.model)
    dst = REPO / args.out if not Path(args.out).is_absolute() else Path(args.out)
    if not src.exists():
        raise SystemExit(f"✖ {src} not found")

    print(f"\n▶ static INT8 quantization")
    print(f"  source : {src.name}  ({src.stat().st_size / 1e6:.2f} MB)")

    session = ort.InferenceSession(str(src), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    del session

    video = REPO / args.calib_video if args.calib_video else None
    frames = load_calibration_frames(video, args.calib_frames)
    print(f"  calib  : {len(frames)} frames from "
          f"{video.name if video and video.exists() else 'data/demo_images'}")

    # Pre-process the graph first. Static quantization needs known shapes, and
    # skipping this step is the usual cause of "quantization produced a model
    # that runs but is wrong" — unfolded constants and missing shapes leave ops
    # unquantized or mis-scaled.
    prepped = dst.with_name(dst.stem + "_prepped.onnx")
    print("  running quant_pre_process (shape inference + constant folding)…")
    try:
        quant_pre_process(str(src), str(prepped), skip_symbolic_shape=False)
        model_for_quant = prepped
    except Exception as e:
        print(f"  ⚠ pre-process failed ({e}); quantizing the raw graph instead")
        model_for_quant = src

    reader = FrameCalibrationReader(frames, input_name, args.input_size)

    exclude: list[str] = []
    if not args.quantize_head:
        exclude, prefix = find_detection_head_nodes(model_for_quant)
        print(f"  excluding the detection head from quantization: "
              f"{len(exclude)} nodes under {prefix or '(graph tail)'}")
        print("    (quantizing the head yields a model that detects nothing — "
              "box/DFL activations do not fit in 256 levels)")

    print(f"  quantizing to {args.format.upper()}, "
          f"per-channel={args.per_channel}, MinMax calibration…")
    try:
        quantize_static(
            model_input=str(model_for_quant),
            model_output=str(dst),
            calibration_data_reader=reader,
            quant_format=QuantFormat.QDQ if args.format == "qdq" else QuantFormat.QOperator,
            # Weights signed, activations unsigned: the combination CPU and most
            # NPU kernels are optimised for. Signed activations force a slower
            # generic path on several backends.
            weight_type=QuantType.QInt8,
            activation_type=QuantType.QUInt8,
            per_channel=args.per_channel,
            calibrate_method=CalibrationMethod.MinMax,
            # Never quantize these. Sigmoid/Mul/Add carry the detection head's
            # box and keypoint decode, where int8 rounding shows up directly as
            # jittered coordinates.
            nodes_to_exclude=exclude,
            extra_options={"ActivationSymmetric": False, "WeightSymmetric": True},
        )
    except Exception as e:
        raise SystemExit(f"✖ quantization failed: {e}")
    finally:
        if prepped.exists():
            prepped.unlink()
        # quant_pre_process can leave an external-data sidecar next to the temp file
        for stray in dst.parent.glob(prepped.stem + "*"):
            if stray != dst:
                try:
                    stray.unlink()
                except OSError:
                    pass

    print(f"\n  output : {dst.name}  ({dst.stat().st_size / 1e6:.2f} MB)")

    # Report the graph so the caller can see the fused kernels actually appeared,
    # rather than trusting that "quantize_static" did what its name says.
    try:
        import collections
        import onnx
        ops = collections.Counter(n.op_type for n in onnx.load(str(dst)).graph.node)
        print(f"  nodes  : {sum(ops.values())}")
        for op in ("QLinearConv", "ConvInteger", "DynamicQuantizeLinear",
                   "QuantizeLinear", "DequantizeLinear", "Conv"):
            if ops.get(op):
                print(f"    {op:<24}{ops[op]}")
        if ops.get("DynamicQuantizeLinear"):
            print("\n  ⚠ DynamicQuantizeLinear is still present — the graph did not "
                  "fully statically quantize. Check that quant_pre_process succeeded.")
        elif ops.get("QLinearConv") or (ops.get("QuantizeLinear") and not ops.get("Conv")):
            print("\n  ✔ statically quantized: no per-inference scale computation.")
    except ImportError:
        pass

    print(f"\n  Now verify it is genuinely faster AND still accurate:")
    print(f"    python scripts/benchmark_edge.py --int8 {dst.relative_to(REPO).as_posix()}")
    print(f"\n  A smaller file is not the goal — a faster, NPU-consumable file is.")
    print(f"  If this is not faster than FP32, do not ship it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
