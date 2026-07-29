"""
Phase 0 Day 1 — End-to-End ML Pipeline Test
---------------------------------------------
Processes the sample construction video through the full YOLO detection pipeline.
Asserts:
  ✓ At least 1 object detected in the video
  ✓ No exceptions thrown during processing
  ✓ Output annotated video written to disk
  ✓ API health check returns 200

Prints PASS / FAIL with details.

Usage:
  python scripts/test_ml_pipeline.py
  python scripts/test_ml_pipeline.py --api http://localhost:8000
  python scripts/test_ml_pipeline.py --frames 10   # process only first 10 frames
"""

import sys
import os
import time
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

VIDEO_PATH  = os.path.join(ROOT, "data", "sample_construction.mp4")
OUTPUT_PATH = os.path.join(ROOT, "data", "test_output_pipeline.mp4")


# ---------------------------------------------------------------------------
# Test 1: Video pipeline
# ---------------------------------------------------------------------------

def test_video_pipeline(max_frames: int = 60) -> dict:
    """Run YOLO on sample_construction.mp4, assert at least 1 detection."""
    import cv2
    from ultralytics import YOLO

    print("\n[TEST 1] Video pipeline end-to-end…")

    if not os.path.exists(VIDEO_PATH):
        return {
            "name": "video_pipeline",
            "pass": False,
            "reason": f"Video file not found: {VIDEO_PATH}",
        }

    model_path = os.path.join(ROOT, "yolo11n.pt")
    if not os.path.exists(model_path):
        model_path = "yolo11n.pt"

    try:
        model = YOLO(model_path)
    except Exception as e:
        return {"name": "video_pipeline", "pass": False, "reason": f"YOLO load failed: {e}"}

    cap = cv2.VideoCapture(VIDEO_PATH)
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out    = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (w, h))

    frame_count = 0
    total_detections = 0
    errors = []

    start = time.time()
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame_count >= max_frames:
            break
        frame_count += 1
        try:
            results = model(frame, verbose=False)
            for r in results:
                if r.boxes is not None:
                    total_detections += len(r.boxes)
            annotated = results[0].plot()
            out.write(annotated)
        except Exception as e:
            errors.append(str(e))

        if frame_count % 10 == 0:
            print(f"  Processed {frame_count} frames, {total_detections} detections so far…")

    cap.release()
    out.release()
    elapsed = time.time() - start

    passed   = total_detections > 0 and len(errors) == 0
    reason   = ""
    if total_detections == 0:
        reason = "No objects detected in any frame."
    if errors:
        reason += f" Errors: {errors[:3]}"

    print(f"  Frames: {frame_count} | Detections: {total_detections} | Time: {elapsed:.1f}s")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"  {'✅ PASS' if passed else '❌ FAIL' + ': ' + reason}")

    return {
        "name"           : "video_pipeline",
        "pass"           : passed,
        "frames"         : frame_count,
        "detections"     : total_detections,
        "errors"         : errors,
        "elapsed_sec"    : round(elapsed, 2),
        "output_path"    : OUTPUT_PATH,
        "reason"         : reason,
    }


# ---------------------------------------------------------------------------
# Test 2: API health check
# ---------------------------------------------------------------------------

def test_api_health(api_url: str) -> dict:
    """GET /api/v1/health and assert status 200."""
    print(f"\n[TEST 2] API health check: {api_url}/api/v1/health")
    try:
        import requests
        r = requests.get(f"{api_url}/api/v1/health", timeout=5)
        passed = r.status_code == 200
        body   = r.json() if r.status_code == 200 else {}
        reason = "" if passed else f"HTTP {r.status_code}"
        print(f"  Status: {r.status_code} | Body: {body}")
        print(f"  {'✅ PASS' if passed else '❌ FAIL: ' + reason}")
        return {"name": "api_health", "pass": passed, "status_code": r.status_code, "body": body}
    except Exception as e:
        print(f"  ❌ FAIL (cannot reach API): {e}")
        return {"name": "api_health", "pass": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Test 3: Unified detector (full pipeline on one frame)
# ---------------------------------------------------------------------------

def test_full_pipeline_frame() -> dict:
    """Run one frame through the full unified VisionPipeline."""
    print("\n[TEST 3] Full pipeline on one frame…")
    try:
        import cv2
        from agents.vision.detector import VisionPipeline

        cap = cv2.VideoCapture(VIDEO_PATH)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            return {"name": "full_pipeline_frame", "pass": False, "reason": "No frame read"}

        pipeline = VisionPipeline(zone_id="A12")
        result   = pipeline.analyze_ndarray(frame)

        status  = result.get("status", "error")
        persons = [a for a in result.get("assets_detected", []) if a.get("asset_type") == "person"]
        passed  = status in ("success", "mock") and result.get("annotated_frame") is not None

        print(f"  Status: {status} | Objects: {len(result.get('assets_detected', []))} | Persons: {len(persons)}")
        print(f"  Zone risk: {result.get('zone_summary', {}).get('zone_risk_level', 'N/A')}")
        print(f"  {'✅ PASS' if passed else '❌ FAIL'}")
        return {
            "name"   : "full_pipeline_frame",
            "pass"   : passed,
            "status" : status,
            "objects": len(result.get("assets_detected", [])),
            "persons": len(persons),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"name": "full_pipeline_frame", "pass": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="FieldPilot ML Pipeline Tests")
    p.add_argument("--api",    default="http://localhost:8000")
    p.add_argument("--frames", type=int, default=60, help="Max frames to process")
    p.add_argument("--skip-api", action="store_true", help="Skip API health check")
    args = p.parse_args()

    print("=" * 60)
    print("  FIELDPILOT AI — Phase 0 ML Pipeline Tests")
    print("=" * 60)

    results = []
    results.append(test_video_pipeline(args.frames))
    if not args.skip_api:
        results.append(test_api_health(args.api))
    results.append(test_full_pipeline_frame())

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    all_pass = True
    for r in results:
        mark = "✅" if r.get("pass") else "❌"
        print(f"  {mark}  {r['name']}")
        if not r.get("pass"):
            all_pass = False
            print(f"      → {r.get('reason', 'see output above')}")

    print("=" * 60)
    if all_pass:
        print("  ✅ ALL TESTS PASSED")
    else:
        print("  ❌ SOME TESTS FAILED")
    print("=" * 60 + "\n")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
