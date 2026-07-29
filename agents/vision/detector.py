"""
Vision Detector — FieldPilot AI (Unified Pipeline)
-----------------------------------------------------
Orchestrates the full Tier 1 ML stack:
  1. YOLO11n  + BoT-SORT  → person/object detection + tracking
  2. PpeDetector           → full PPE check per person crop
  3. PoseEstimator         → 17-keypoint pose + fall + head-yaw
  4. HazardAnalyzer        → fused risk score 0–100

The VisionPipeline.analyze_frame() method accepts either:
  - str  : path to an image/video frame on disk
  - ndarray: raw BGR frame (for live streaming)

Returns a unified payload that the API and live pipeline both consume.
"""

import os
import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()
MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "yolo11n.pt")

from agents.vision.ppe_detector   import PpeDetector
from agents.vision.pose_estimator import PoseEstimator
from agents.vision.hazard_analyzer import HazardAnalyzer
from agents.vision.attention_tracker import AttentionStateMachine


class VisionPipeline:
    """
    Full ML detection pipeline.
    Thread-safe for single-threaded use; instantiate once per process.
    """

    def __init__(self, zone_id: str = "A12"):
        self.zone_id = zone_id
        self.yolo    = None
        self.ppe     = PpeDetector()
        self.pose    = PoseEstimator()
        self.hazard  = HazardAnalyzer()
        # One tracker per pipeline instance, reused every frame — the Day-4
        # dwell-time state machine needs its per-track_id history to persist
        # across calls, not get reset each frame.
        self.attention_tracker = AttentionStateMachine()
        self._load_yolo()

    def _load_yolo(self):
        try:
            from ultralytics import YOLO
            path = MODEL_PATH if os.path.exists(MODEL_PATH) else "yolo11n.pt"
            self.yolo = YOLO(path)
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            self.yolo(dummy, verbose=False)
            print(f"[DETECTOR] YOLO loaded from {path}")
        except Exception as e:
            print(f"[DETECTOR] ⚠ YOLO load failed: {e}")
            self.yolo = None

    def _try_track(self, frame: np.ndarray):
        """
        Attempt BoT-SORT tracking; fall back to plain predict() if lap is unavailable.
        Also patches lap→lapx so ultralytics can find the Windows-compatible package.
        """
        # Ensure lapx is importable as 'lap' for ultralytics internals
        try:
            import lap  # noqa: F401
        except ModuleNotFoundError:
            try:
                import lapx as lap  # noqa: F401
                import sys as _sys
                _sys.modules.setdefault("lap", lap)
            except ImportError:
                pass

        try:
            return self.yolo.track(
                frame,
                persist=True,
                tracker="botsort.yaml",
                verbose=False,
                conf=0.30,
            )
        except Exception as track_err:
            if "lap" in str(track_err).lower() or "modulenotfounderror" in str(track_err).lower():
                print(f"[DETECTOR] BoT-SORT unavailable ({track_err}), using predict() fallback")
                return self.yolo.predict(frame, verbose=False, conf=0.30)
            raise

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def analyze_frame(self, source) -> dict:
        """
        Accept either a file path (str) or raw BGR ndarray.
        Returns the unified detection payload.
        """
        if isinstance(source, str):
            frame = cv2.imread(source)
            if frame is None:
                return self._mock_response(source)
        elif isinstance(source, np.ndarray):
            frame = source
        else:
            return self._mock_response("")

        return self._run_pipeline(frame)

    def analyze_ndarray(self, frame: np.ndarray) -> dict:
        """Convenience wrapper accepting raw BGR frames."""
        return self._run_pipeline(frame)

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(self, frame: np.ndarray) -> dict:
        if self.yolo is None:
            return self._mock_response("")

        try:
            # ── Step 1: YOLO detection + BoT-SORT tracking ─────────────
            results = self._try_track(frame)

            persons     = []
            other_items = []

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue
                for i, box in enumerate(boxes):
                    cls_id     = int(box.cls[0].item())
                    confidence = float(box.conf[0].item())
                    coords     = box.xyxy[0].tolist()
                    class_name = result.names[cls_id]
                    track_id   = int(box.id[0].item()) if box.id is not None else None
                    asset_id   = f"{class_name}_{track_id}" if track_id else f"asset_{i}"

                    asset = {
                        "asset_id"    : asset_id,
                        "asset_type"  : class_name,
                        "confidence"  : round(confidence, 3),
                        "track_id"    : track_id,
                        "bounding_box": {
                            "x1": coords[0], "y1": coords[1],
                            "x2": coords[2], "y2": coords[3],
                        },
                        "ppe_status"  : None,
                        "pose"        : None,
                    }

                    if class_name == "person":
                        persons.append(asset)
                    else:
                        other_items.append(asset)

            # ── Step 2: PPE detection on person crops ───────────────────
            for p in persons:
                p["ppe_status"] = self.ppe.check_worker(
                    frame, p["bounding_box"], p.get("track_id")
                )

            # ── Step 3: Pose estimation ─────────────────────────────────
            track_ids  = [p.get("track_id") for p in persons]
            pose_results = self.pose.analyze_frame(frame, track_ids)

            # Match pose results back to persons by track_id, then by index
            pose_by_tid: dict = {
                pr["track_id"]: pr for pr in pose_results if pr.get("track_id")
            }
            for i, p in enumerate(persons):
                tid = p.get("track_id")
                if tid and tid in pose_by_tid:
                    p["pose"] = pose_by_tid[tid]
                elif i < len(pose_results):
                    p["pose"] = pose_results[i]

            # ── Step 4: Hazard assessment ────────────────────────────────
            assessments = self.hazard.analyze_frame(
                zone_id=self.zone_id,
                persons=persons,
                pose_results=pose_results,
                attention_tracker=self.attention_tracker,
            )
            zone_summary = self.hazard.aggregate_zone_risk(assessments)

            # Attach assessment to each person
            assess_by_worker = {a.worker_id: a for a in assessments}
            for p in persons:
                a = assess_by_worker.get(p["asset_id"])
                if a:
                    p["hazard"] = {
                        "score"          : a.hazard_score,
                        "risk_level"     : a.risk_level,
                        "primary_alert"  : a.primary_alert,
                        "warnings"       : a.all_warnings,
                        "fall_detected"  : a.fall_detected,
                        "fire_fall"      : a.fire_fall_alert,
                        "fire_ppe"       : a.fire_ppe_alert,
                        "attention_state": a.attention_state,
                    }

            # ── Build annotated frame ────────────────────────────────────
            annotated = self._annotate(frame.copy(), persons, other_items, zone_summary)

            return {
                "status"           : "success",
                "scene_context"    : "auto_detected",
                "assets_detected"  : persons + other_items,
                "compliance_checks": self._build_compliance_checks(persons),
                "zone_summary"     : zone_summary,
                "fall_events"      : [
                    p["asset_id"] for p in persons
                    if p.get("hazard", {}).get("fall_detected")
                ],
                "annotated_frame"  : annotated,   # ndarray, for live streaming
            }

        except Exception as e:
            print(f"[DETECTOR] Pipeline error: {e}")
            import traceback; traceback.print_exc()
            return self._mock_response("")

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------

    def _annotate(self, frame: np.ndarray, persons: list, others: list,
                  zone_summary: dict) -> np.ndarray:
        """Draw AR-style bounding boxes, PPE badges, fall alerts on frame."""
        h, w = frame.shape[:2]

        RISK_COLORS = {
            "critical": (0,   0, 255),
            "high"    : (0,  80, 255),
            "elevated": (0, 165, 255),
            "normal"  : (0, 200,  80),
        }

        for p in persons:
            bbox  = p.get("bounding_box", {})
            x1, y1 = int(bbox.get("x1", 0)), int(bbox.get("y1", 0))
            x2, y2 = int(bbox.get("x2", w)), int(bbox.get("y2", h))

            hazard     = p.get("hazard", {})
            risk_level = hazard.get("risk_level", "normal")
            color      = RISK_COLORS.get(risk_level, (0, 200, 80))

            # Person bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Track ID + risk score
            label = (f"ID:{p.get('track_id','?')}  "
                     f"Risk:{hazard.get('score', 0)}")
            cv2.putText(frame, label, (x1, max(y1 - 8, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2)

            # PPE emoji badge (small text)
            ppe  = p.get("ppe_status", {})
            if ppe:
                from agents.vision.ppe_detector import PpeDetector as _PPE
                badge = _PPE.ppe_emoji_summary(ppe)
                # Draw badge below bounding box
                cv2.putText(frame, badge, (x1, min(y2 + 18, h - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 220), 1)

            # Fall alert overlay
            if hazard.get("fall_detected"):
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 4)
                cv2.putText(frame, "⚠ FALL", (x1, y1 + 30),
                            cv2.FONT_HERSHEY_DUPLEX, 0.9, (0, 0, 255), 2)

            # Pose skeleton — draw available keypoints
            pose = p.get("pose", {})
            if pose and pose.get("keypoints"):
                kpts = pose["keypoints"]
                for kp in kpts:
                    kx, ky, kconf = kp["x"], kp["y"], kp["confidence"]
                    if kconf > 0.3 and kx > 0 and ky > 0:
                        cv2.circle(frame, (int(kx), int(ky)), 3, (0, 255, 255), -1)

        # Other objects (rebar, tools, etc.)
        for obj in others:
            bbox = obj.get("bounding_box", {})
            x1, y1 = int(bbox.get("x1", 0)), int(bbox.get("y1", 0))
            x2, y2 = int(bbox.get("x2", w)), int(bbox.get("y2", h))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (100, 200, 255), 1)
            cv2.putText(frame, obj.get("asset_type", "?"),
                        (x1, max(y1 - 5, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (100, 200, 255), 1)

        # Top HUD
        zone_risk = zone_summary.get("zone_risk_level", "normal")
        hud_color = RISK_COLORS.get(zone_risk, (0, 200, 80))
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 56), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
        cv2.putText(frame, f"FIELDPILOT AI  |  Zone {self.zone_id}",
                    (12, 22), cv2.FONT_HERSHEY_DUPLEX, 0.65, (255, 255, 255), 1)
        cv2.putText(frame,
                    f"Risk: {zone_risk.upper()}  |  "
                    f"Workers: {zone_summary.get('worker_count', 0)}  |  "
                    f"Falls: {zone_summary.get('fall_events', 0)}  |  "
                    f"PPE Issues: {zone_summary.get('ppe_violations', 0)}",
                    (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.45, hud_color, 1)

        return frame

    # ------------------------------------------------------------------
    # Compliance helpers
    # ------------------------------------------------------------------

    def _build_compliance_checks(self, persons: list) -> list:
        checks = []
        for p in persons:
            ppe  = p.get("ppe_status", {})
            haz  = p.get("hazard", {})
            pose = p.get("pose", {})
            if not ppe:
                continue
            checks.append({
                "worker_id"      : p["asset_id"],
                "hardhat"        : ppe.get("hardhat"),
                "vest"           : ppe.get("vest"),
                "gloves"         : ppe.get("gloves"),
                "glasses"        : ppe.get("glasses"),
                "boots"          : ppe.get("boots"),
                "ppe_score"      : ppe.get("ppe_score"),
                "fall_detected"  : pose.get("fall_detected") if pose else False,
                "risk_level"     : haz.get("risk_level", "normal"),
                "hazard_score"   : haz.get("score", 0),
                "attention_state": haz.get("attention_state", "PASSIVE"),
            })
        return checks

    # ------------------------------------------------------------------
    # Mock fallback
    # ------------------------------------------------------------------

    def _mock_response(self, source: str) -> dict:
        return {
            "status"           : "mock",
            "scene_context"    : "mock",
            "assets_detected"  : [],
            "compliance_checks": [],
            "zone_summary"     : {"zone_risk_score": 0, "zone_risk_level": "normal"},
            "fall_events"      : [],
            "annotated_frame"  : None,
        }
