"""
Pose Estimator — FieldPilot AI
--------------------------------
17-keypoint human pose estimation using YOLO11n-pose.
Derives:
  - Fall detection  (hip/shoulder vertical velocity + body angle)
  - Head-yaw gaze   (ear-nose angle → where the worker is looking)
  - Proximity alerts (future: keypoints near danger-zone polygons)

COCO 17-keypoint indices:
  0  nose         1  left_eye     2  right_eye
  3  left_ear     4  right_ear    5  left_shoulder
  6  right_shoulder 7 left_elbow  8  right_elbow
  9  left_wrist  10  right_wrist 11  left_hip
  12 right_hip   13 left_knee    14 right_knee
  15 left_ankle  16 right_ankle
"""

import os
import math
import time
import collections
import numpy as np
from typing import Optional

POSE_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "weights", "yolo11n-pose.pt"
)
POSE_CONF_THRESHOLD = 0.35

# Keypoint indices
KP_NOSE = 0
KP_LEFT_EAR = 3
KP_RIGHT_EAR = 4
KP_LEFT_SHOULDER = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_HIP = 11
KP_RIGHT_HIP = 12
KP_LEFT_ANKLE = 15
KP_RIGHT_ANKLE = 16

# Fall detection thresholds
FALL_ANGLE_THRESHOLD = 45.0       # degrees: body tilted more than this → fall candidate
FALL_VELOCITY_THRESHOLD = 60.0    # px/frame: fast downward hip motion → fall
FALL_CONFIRM_FRAMES = 3           # consecutive frames to confirm fall
HISTORY_FRAMES = 10               # frames of history per track id

# Head-yaw thresholds (degrees)
YAW_LOOKING_AWAY = 30.0   # more than 30° sideways = looking away from work
YAW_MAX = 90.0


class PoseEstimator:
    """
    Runs YOLO11n-pose on each frame and produces per-person pose analysis.
    Maintains a rolling history per track_id for velocity-based fall detection.
    """

    def __init__(self):
        self.model = None
        # Rolling history: track_id → deque of (timestamp, mid_hip_y)
        self._hip_history: dict[int, collections.deque] = {}
        # Fall state: track_id → int (consecutive fall frames)
        self._fall_frames: dict[int, int] = {}
        self._load_model()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        try:
            from ultralytics import YOLO
            print("[POSE] Loading YOLO11n-pose model…")
            # Auto-downloads yolo11n-pose.pt from ultralytics CDN if not local
            model_path = POSE_MODEL_PATH if os.path.exists(POSE_MODEL_PATH) else "yolo11n-pose.pt"
            self.model = YOLO(model_path)
            # Copy to models/weights for next run
            if not os.path.exists(POSE_MODEL_PATH):
                import shutil
                src = "yolo11n-pose.pt"
                if os.path.exists(src):
                    os.makedirs(os.path.dirname(POSE_MODEL_PATH), exist_ok=True)
                    shutil.copy(src, POSE_MODEL_PATH)
            # Warm-up
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            self.model(dummy, verbose=False)
            print("[POSE] Model ready.")
        except Exception as e:
            print(f"[POSE] ⚠ Could not load pose model: {e}. Running in mock mode.")
            self.model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_frame(self, frame: np.ndarray, existing_track_ids: Optional[list[int]] = None) -> list[dict]:
        """
        Run pose estimation on a full frame.

        Returns:
            List of per-person pose results:
            {
              'track_id': int | None,
              'keypoints': list[{x, y, confidence}],   # 17 keypoints
              'fall_detected': bool,
              'fall_confidence': float,
              'head_yaw_deg': float,
              'looking_away': bool,
              'body_angle_deg': float,
              'mid_hip': {x, y},
              'warnings': list[str]
            }
        """
        if self.model is None:
            return self._mock_results(existing_track_ids)

        try:
            # Patch lapx → lap for ultralytics BoT-SORT on Windows
            try:
                import lap  # noqa: F401
            except ModuleNotFoundError:
                try:
                    import lapx as _lapx
                    import sys as _sys
                    _sys.modules.setdefault("lap", _lapx)
                except ImportError:
                    pass

            try:
                results = self.model.track(
                    frame, persist=True, conf=POSE_CONF_THRESHOLD,
                    tracker="botsort.yaml", verbose=False
                )
            except Exception as track_err:
                if "lap" in str(track_err).lower():
                    results = self.model.predict(frame, conf=POSE_CONF_THRESHOLD, verbose=False)
                else:
                    raise

            persons = []
            now = time.time()

            for r in results:
                if r.keypoints is None:
                    continue

                kps_data = r.keypoints.data  # (N, 17, 3) — x, y, conf
                boxes = r.boxes

                for i in range(len(kps_data)):
                    kps = kps_data[i].cpu().numpy()  # (17, 3)
                    track_id = None
                    if boxes is not None and boxes.id is not None and i < len(boxes.id):
                        track_id = int(boxes.id[i].item())

                    person_result = self._analyze_person(kps, track_id, now)
                    persons.append(person_result)

            return persons

        except Exception as e:
            print(f"[POSE] Inference error: {e}")
            return self._mock_results(existing_track_ids)

    # ------------------------------------------------------------------
    # Per-person analysis
    # ------------------------------------------------------------------

    def _analyze_person(self, kps: np.ndarray, track_id: Optional[int], timestamp: float) -> dict:
        """Analyse a single person's keypoints."""
        keypoints = [
            {"x": float(kps[i, 0]), "y": float(kps[i, 1]), "confidence": float(kps[i, 2])}
            for i in range(len(kps))
        ]

        # Midpoints
        mid_hip = self._midpoint(kps, KP_LEFT_HIP, KP_RIGHT_HIP)
        mid_shoulder = self._midpoint(kps, KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER)
        mid_ankle = self._midpoint(kps, KP_LEFT_ANKLE, KP_RIGHT_ANKLE)

        # Body angle (vertical = 0°, horizontal = 90°)
        body_angle = self._body_angle(mid_shoulder, mid_hip)

        # Head yaw (ear-nose angle)
        head_yaw = self._head_yaw(kps)

        # Fall detection
        fall_detected, fall_conf = self._detect_fall(track_id, mid_hip, body_angle, timestamp)

        warnings = []
        if fall_detected:
            warnings.append("⚠ FALL DETECTED")
        if abs(head_yaw) > YAW_LOOKING_AWAY:
            warnings.append(f"HEAD TURNED {abs(head_yaw):.0f}°")

        return {
            "track_id": track_id,
            "keypoints": keypoints,
            "fall_detected": fall_detected,
            # float() before round() — round() on a numpy scalar returns
            # another numpy scalar (still not JSON-serializable), not a
            # native Python float, same root cause as mid_hip/mid_shoulder
            # above.
            "fall_confidence": round(float(fall_conf), 3),
            "head_yaw_deg": round(float(head_yaw), 1),
            "looking_away": bool(abs(head_yaw) > YAW_LOOKING_AWAY),
            "body_angle_deg": round(float(body_angle), 1),
            # float() — mid_hip/mid_shoulder come from _midpoint() on raw
            # numpy keypoint arrays (numpy.float32), which json.dumps()
            # cannot serialize. Caught live during a sustained pipeline
            # rehearsal: every frame with a detected person crashed the
            # offline-queue fallback path with "Object of type float32 is
            # not JSON serializable" the moment the primary POST failed.
            "mid_hip": {"x": float(mid_hip[0]), "y": float(mid_hip[1])},
            "mid_shoulder": {"x": float(mid_shoulder[0]), "y": float(mid_shoulder[1])},
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Fall detection
    # ------------------------------------------------------------------

    def _detect_fall(
        self,
        track_id: Optional[int],
        mid_hip: tuple,
        body_angle: float,
        timestamp: float,
    ) -> tuple[bool, float]:
        """
        Two-condition fall detector:
        1. Body angle > FALL_ANGLE_THRESHOLD (person is horizontal)
        2. Hip moving downward quickly (velocity-based)
        Both must be true for FALL_CONFIRM_FRAMES consecutive frames.
        """
        if track_id is None:
            # Can't track without an ID — rely on angle only
            angle_fall = body_angle > FALL_ANGLE_THRESHOLD
            return angle_fall, 0.6 if angle_fall else 0.0

        # Maintain history
        if track_id not in self._hip_history:
            self._hip_history[track_id] = collections.deque(maxlen=HISTORY_FRAMES)
            self._fall_frames[track_id] = 0

        history = self._hip_history[track_id]
        history.append((timestamp, mid_hip[1]))  # store y-coordinate

        # Compute velocity
        velocity = 0.0
        if len(history) >= 2:
            dt = history[-1][0] - history[-2][0]
            dy = history[-1][1] - history[-2][1]
            velocity = dy / max(dt, 1e-6)  # px/sec downward is positive

        # Angle condition
        angle_condition = body_angle > FALL_ANGLE_THRESHOLD
        # Velocity condition: fast downward motion
        velocity_condition = velocity > FALL_VELOCITY_THRESHOLD

        # Must satisfy both OR extreme angle alone
        is_fall_frame = angle_condition and (velocity_condition or body_angle > 70)

        if is_fall_frame:
            self._fall_frames[track_id] = min(
                self._fall_frames[track_id] + 1, FALL_CONFIRM_FRAMES
            )
        else:
            self._fall_frames[track_id] = max(self._fall_frames[track_id] - 1, 0)

        fall_confirmed = self._fall_frames[track_id] >= FALL_CONFIRM_FRAMES
        confidence = self._fall_frames[track_id] / FALL_CONFIRM_FRAMES

        return fall_confirmed, confidence

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _midpoint(kps: np.ndarray, idx_a: int, idx_b: int) -> tuple:
        """Return midpoint of two keypoints (x, y). Returns (0,0) if low confidence."""
        conf_a = kps[idx_a, 2] if idx_a < len(kps) else 0
        conf_b = kps[idx_b, 2] if idx_b < len(kps) else 0
        if conf_a < 0.3 and conf_b < 0.3:
            return (0.0, 0.0)
        if conf_a < 0.3:
            return (float(kps[idx_b, 0]), float(kps[idx_b, 1]))
        if conf_b < 0.3:
            return (float(kps[idx_a, 0]), float(kps[idx_a, 1]))
        return (
            (kps[idx_a, 0] + kps[idx_b, 0]) / 2,
            (kps[idx_a, 1] + kps[idx_b, 1]) / 2,
        )

    @staticmethod
    def _body_angle(shoulder: tuple, hip: tuple) -> float:
        """
        Angle of torso from vertical (0° = upright, 90° = lying flat).
        """
        dx = shoulder[0] - hip[0]
        dy = shoulder[1] - hip[1]  # negative = shoulder above hip (normal)
        if abs(dx) < 1e-3 and abs(dy) < 1e-3:
            return 0.0
        # Angle of spine vector from vertical axis
        angle = math.degrees(math.atan2(abs(dx), abs(dy)))
        return angle

    @staticmethod
    def _head_yaw(kps: np.ndarray) -> float:
        """
        Estimate head yaw from ear-nose geometry.
        Positive = turned right, Negative = turned left.
        Returns 0 if keypoints not visible.
        """
        nose_conf = kps[KP_NOSE, 2] if len(kps) > KP_NOSE else 0
        left_ear_conf = kps[KP_LEFT_EAR, 2] if len(kps) > KP_LEFT_EAR else 0
        right_ear_conf = kps[KP_RIGHT_EAR, 2] if len(kps) > KP_RIGHT_EAR else 0

        if nose_conf < 0.3:
            return 0.0

        nose_x = kps[KP_NOSE, 0]

        if left_ear_conf > 0.3 and right_ear_conf > 0.3:
            # Both ears visible — nose should be centred
            ear_mid_x = (kps[KP_LEFT_EAR, 0] + kps[KP_RIGHT_EAR, 0]) / 2
            ear_width = abs(kps[KP_RIGHT_EAR, 0] - kps[KP_LEFT_EAR, 0])
            if ear_width < 1:
                return 0.0
            offset = (nose_x - ear_mid_x) / ear_width
            yaw = offset * YAW_MAX
            return float(np.clip(yaw, -YAW_MAX, YAW_MAX))

        elif right_ear_conf > 0.3:
            # Only right ear visible → head turned right
            dx = nose_x - kps[KP_RIGHT_EAR, 0]
            yaw = min(max(dx / 30, 0), YAW_MAX)
            return float(yaw)

        elif left_ear_conf > 0.3:
            # Only left ear visible → head turned left
            dx = kps[KP_LEFT_EAR, 0] - nose_x
            yaw = -min(max(dx / 30, 0), YAW_MAX)
            return float(yaw)

        return 0.0

    # ------------------------------------------------------------------
    # Mock mode
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_results(track_ids: Optional[list[int]] = None) -> list[dict]:
        """Return plausible mock results when model is unavailable."""
        mock_id = (track_ids[0] if track_ids else 1)
        return [
            {
                "track_id": mock_id,
                "keypoints": [{"x": 0.0, "y": 0.0, "confidence": 0.0}] * 17,
                "fall_detected": False,
                "fall_confidence": 0.0,
                "head_yaw_deg": 0.0,
                "looking_away": False,
                "body_angle_deg": 5.0,
                "mid_hip": {"x": 320, "y": 400},
                "mid_shoulder": {"x": 320, "y": 280},
                "warnings": [],
            }
        ]

    def reset_track(self, track_id: int):
        """Clear history for a lost track."""
        self._hip_history.pop(track_id, None)
        self._fall_frames.pop(track_id, None)
