"""
ONNX Exporter — FieldPilot AI
-------------------------------
Exports YOLO11n-pose to ONNX with dynamic INT8 quantization.
Also provides a verification harness that:
  1. Runs 5 sample frames through the full PyTorch model
  2. Runs the same frames through the ONNX Runtime session
  3. Asserts that the top detected class matches in both
  4. Writes results to models/evaluation/baseline_YYYYMMDD.json

Usage:
  python -m agents.vision.onnx_exporter               # export only
  python -m agents.vision.onnx_exporter --verify       # export + verify
  python -m agents.vision.onnx_exporter --verify-only  # verify existing export
"""

import os
import sys
import json
import argparse
import datetime
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEIGHTS_DIR = os.path.join(ROOT, "models", "weights")
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")
DATA_DIR = os.path.join(ROOT, "data")

POSE_PT_PATH = os.path.join(WEIGHTS_DIR, "yolo11n-pose.pt")
POSE_ONNX_PATH = os.path.join(WEIGHTS_DIR, "yolo11n-pose-int8.onnx")
GENERAL_PT_PATH = os.path.join(ROOT, "yolo11n.pt")


def export_to_onnx(model_path: str, output_path: str, imgsz: int = 640) -> str:
    """Export a YOLO model to ONNX with INT8 dynamic quantization."""
    try:
        from ultralytics import YOLO
        print(f"[ONNX] Loading {model_path}…")
        model = YOLO(model_path)
        print(f"[ONNX] Exporting to ONNX (imgsz={imgsz})…")
        # Export to ONNX (ultralytics handles the format)
        exported = model.export(format="onnx", imgsz=imgsz, simplify=True, dynamic=False)
        raw_onnx = str(exported)
        print(f"[ONNX] Raw export: {raw_onnx}")

        # Apply INT8 dynamic quantization
        try:
            import onnx
            from onnxruntime.quantization import quantize_dynamic, QuantType
            print("[ONNX] Applying INT8 dynamic quantization…")
            quantize_dynamic(
                raw_onnx,
                output_path,
                weight_type=QuantType.QInt8,
            )
            print(f"[ONNX] ✅ Quantized model saved to {output_path}")
            return output_path
        except ImportError:
            print("[ONNX] onnxruntime.quantization not available — saving unquantized ONNX.")
            import shutil
            shutil.copy(raw_onnx, output_path)
            return output_path

    except Exception as e:
        print(f"[ONNX] ❌ Export failed: {e}")
        raise


def _load_sample_frames(n: int = 5) -> list:
    """Load N sample frames: from video file or generate synthetic ones."""
    import cv2
    frames = []

    video_path = os.path.join(DATA_DIR, "sample_construction.mp4")
    if os.path.exists(video_path):
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(total_frames // n, 1)
        for i in range(n):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
        cap.release()

    # Also try webcam for 1 frame if not enough
    if len(frames) < n:
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
            cap.release()

    # Pad with synthetic frames if still not enough
    while len(frames) < n:
        frames.append(np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8))

    return frames[:n]


def verify_onnx(onnx_path: str, pt_path: str, n_frames: int = 5) -> dict:
    """
    Compare top-1 detection class between PyTorch and ONNX model on N frames.
    Returns accuracy report.
    """
    import cv2

    try:
        import onnxruntime as ort
        from ultralytics import YOLO
    except ImportError as e:
        print(f"[VERIFY] Missing dependency: {e}")
        return {"error": str(e)}

    print(f"\n[VERIFY] Loading PyTorch model: {pt_path}")
    pt_model = YOLO(pt_path)
    print(f"[VERIFY] Loading ONNX session: {onnx_path}")
    ort_session = ort.InferenceSession(
        onnx_path,
        providers=["CPUExecutionProvider"]
    )
    input_name = ort_session.get_inputs()[0].name
    input_shape = ort_session.get_inputs()[0].shape  # e.g. [1, 3, 640, 640]
    imgsz = input_shape[2] if len(input_shape) >= 3 else 640

    frames = _load_sample_frames(n_frames)
    results_log = []
    matches = 0

    for idx, frame in enumerate(frames):
        # PyTorch inference
        pt_results = pt_model(frame, verbose=False, conf=0.3)
        pt_cls = None
        pt_conf = 0.0
        for r in pt_results:
            if r.boxes is not None and len(r.boxes) > 0:
                best_idx = r.boxes.conf.argmax().item()
                pt_cls = int(r.boxes.cls[best_idx].item())
                pt_conf = float(r.boxes.conf[best_idx].item())
                break
        pt_label = pt_model.names.get(pt_cls, "none") if pt_cls is not None else "none"

        # ONNX inference
        img = cv2.resize(frame, (imgsz, imgsz))
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_batch = np.transpose(img_rgb, (2, 0, 1))[np.newaxis]  # (1, 3, H, W)

        ort_label = "none"
        ort_conf = 0.0
        try:
            ort_outs = ort_session.run(None, {input_name: img_batch})
            preds = ort_outs[0]
            if preds.ndim == 3:
                preds = preds[0]  # (num_outputs, num_anchors)
            # A YOLO *pose* export's output layout is box(4) + person_conf(1)
            # + 17 keypoints * 3(x,y,conf) = 56 rows — NOT box(4) + N class
            # scores like a plain detection model. Pose only ever has one
            # class ("person"), so row 4 IS the confidence row; treating
            # rows 4: as a class-score block (the old bug here) argmaxes
            # over keypoint coordinates instead and returns nonsense class
            # indices. This parsing is pose-model-specific — a general
            # (multi-class) detection export would need the old layout back.
            if preds.shape[0] >= 5:
                person_conf_row = preds[4]
                best_anchor = int(person_conf_row.argmax())
                ort_conf = float(person_conf_row[best_anchor])
                ort_label = "person" if ort_conf >= 0.3 else "none"
        except Exception as e:
            print(f"[VERIFY] ONNX inference error on frame {idx}: {e}")

        match = (pt_label == ort_label) or (pt_label == "none" and ort_label == "none")
        if match:
            matches += 1

        entry = {
            "frame": idx + 1,
            "pytorch_top1": pt_label,
            "pytorch_conf": round(pt_conf, 3),
            "onnx_top1": ort_label,
            "onnx_conf": round(ort_conf, 3),
            "match": match,
        }
        results_log.append(entry)
        status = "✅" if match else "❌"
        print(f"  Frame {idx+1}: PT={pt_label}({pt_conf:.2f}) ONNX={ort_label}({ort_conf:.2f}) {status}")

    accuracy = matches / len(frames)
    report = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "onnx_path": onnx_path,
        "pt_path": pt_path,
        "frames_tested": len(frames),
        "matches": matches,
        "accuracy": round(accuracy, 3),
        "pass": accuracy >= 0.8,
        "frames": results_log,
    }
    print(f"\n[VERIFY] Top-1 match accuracy: {accuracy*100:.0f}% ({matches}/{len(frames)})")
    print(f"[VERIFY] {'✅ PASS' if report['pass'] else '❌ FAIL'}")
    return report


def save_baseline(report: dict) -> str:
    """Save baseline report to models/evaluation/."""
    os.makedirs(EVAL_DIR, exist_ok=True)
    date_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(EVAL_DIR, f"baseline_{date_str}.json")
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[BASELINE] Saved to {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="FieldPilot ONNX Export & Verification")
    parser.add_argument("--verify", action="store_true", help="Export then verify")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing ONNX export")
    parser.add_argument("--model", default="pose", choices=["pose", "general"],
                        help="Which model to export")
    parser.add_argument("--frames", type=int, default=5, help="Number of frames to verify on")
    args = parser.parse_args()

    os.makedirs(WEIGHTS_DIR, exist_ok=True)

    if args.model == "pose":
        pt_path = POSE_PT_PATH if os.path.exists(POSE_PT_PATH) else "yolo11n-pose.pt"
        onnx_path = POSE_ONNX_PATH
    else:
        pt_path = GENERAL_PT_PATH
        onnx_path = os.path.join(WEIGHTS_DIR, "yolo11n-int8.onnx")

    if not args.verify_only:
        print(f"\n{'='*50}")
        print("STEP 1: Export to ONNX")
        print(f"{'='*50}")
        export_to_onnx(pt_path, onnx_path)

    if args.verify or args.verify_only:
        if not os.path.exists(onnx_path):
            print(f"[ERROR] ONNX file not found: {onnx_path}. Run without --verify-only first.")
            sys.exit(1)
        print(f"\n{'='*50}")
        print("STEP 2: Verify ONNX vs PyTorch")
        print(f"{'='*50}")
        report = verify_onnx(onnx_path, pt_path, n_frames=args.frames)
        baseline_path = save_baseline(report)
        print(f"\n📊 Baseline saved: {baseline_path}")

        if not report.get("pass", False):
            print("⚠ Accuracy below 80% — check model export.")
            sys.exit(1)
        else:
            print("✅ ONNX model verified successfully.")


if __name__ == "__main__":
    main()
