"""
Heavy Equipment Detector — FieldPilot AI
------------------------------------------
Detects forklifts / heavy equipment on the full frame and flags workers in
close proximity as a "struck-by" hazard — one of OSHA's construction
"Focus Four" hazard categories (Falls, Struck-By, Caught-in/between,
Electrocution), alongside the fall detection (PoseEstimator) and PPE
(PpeDetector) already covered.

Model: keremberke/yolov8n-forklift-detection (HF hub, real fine-tuned
YOLOv8n — classes: forklift, person), same integration pattern as
ppe_detector.py's hard-hat model — local weights first (checked into
models/weights/), HF hub URL as a fallback if the local file is missing.
"""

import os
import numpy as np
from typing import Optional

EQUIPMENT_MODEL_REPO = "keremberke/yolov8n-forklift-detection"
EQUIPMENT_MODEL_NAME = "best.pt"
EQUIPMENT_CONF_THRESH = 0.40

# Distance (pixels, in the source frame) below which a worker is considered
# in the strike zone of detected equipment. Pixel-based rather than a real
# metric distance since this runs on uncalibrated frames (same tradeoff
# agents/measurement/estimator.py documents for its own uncalibrated path) —
# good enough for a proximity *warning*, not a certified clearance figure.
STRUCK_BY_PROXIMITY_PX = 150

_LOCAL_EQUIPMENT_MODEL_PATH = os.getenv(
    "EQUIPMENT_MODEL_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../models/weights/forklift_yolov8n.pt")),
)


class EquipmentDetector:
    def __init__(self):
        self.model = None
        self.class_names: dict[int, str] = {}
        self._load_model()

    def _load_model(self):
        from ultralytics import YOLO

        if os.path.exists(_LOCAL_EQUIPMENT_MODEL_PATH):
            try:
                print(f"[EQUIPMENT] Loading heavy-equipment model from local weights: {_LOCAL_EQUIPMENT_MODEL_PATH}")
                self.model = YOLO(_LOCAL_EQUIPMENT_MODEL_PATH)
                dummy = np.zeros((64, 64, 3), dtype=np.uint8)
                self.model(dummy, verbose=False)
                self.class_names = self.model.names
                print(f"[EQUIPMENT] Model loaded. Classes: {self.class_names}")
                return
            except Exception as e:
                print(f"[EQUIPMENT] ⚠ Local weights failed to load ({e}). Falling back to HF hub.")

        try:
            # NOTE: passing a bare filename URL to ultralytics.YOLO() will
            # silently resolve to any same-named file already present in the
            # current working directory before it downloads — confirmed
            # while wiring this in (a stray weights/best.pt collided with
            # this model's own "best.pt" filename). Download explicitly to
            # a distinctly-named local path instead of trusting that path.
            import requests
            url = f"https://huggingface.co/{EQUIPMENT_MODEL_REPO}/resolve/main/{EQUIPMENT_MODEL_NAME}"
            print(f"[EQUIPMENT] Downloading heavy-equipment model from {url}...")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            os.makedirs(os.path.dirname(_LOCAL_EQUIPMENT_MODEL_PATH), exist_ok=True)
            with open(_LOCAL_EQUIPMENT_MODEL_PATH, "wb") as f:
                f.write(resp.content)
            self.model = YOLO(_LOCAL_EQUIPMENT_MODEL_PATH)
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            self.model(dummy, verbose=False)
            self.class_names = self.model.names
            print(f"[EQUIPMENT] Model loaded. Classes: {self.class_names}")
        except Exception as e:
            print(f"[EQUIPMENT] ⚠ Heavy-equipment model unavailable ({e}). Struck-by detection disabled.")
            self.model = None

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Full-frame equipment detection. Returns [] if the model isn't loaded."""
        if self.model is None:
            return []
        try:
            results = self.model(frame, verbose=False, conf=EQUIPMENT_CONF_THRESH)
        except Exception:
            return []

        equipment = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                label = self.class_names.get(int(box.cls[0].item()), "").lower()
                if label == "person":
                    continue  # persons already come from the primary detector's tracker
                conf = float(box.conf[0].item())
                coords = box.xyxy[0].tolist()
                equipment.append({
                    "equipment_type": label or "equipment",
                    "confidence": round(conf, 3),
                    "bounding_box": {"x1": coords[0], "y1": coords[1], "x2": coords[2], "y2": coords[3]},
                })
        return equipment

    @staticmethod
    def nearest_equipment_distance(person_bbox: dict, equipment: list[dict]) -> Optional[tuple[float, dict]]:
        """Pixel distance from a person's bbox center to the nearest equipment bbox center."""
        if not equipment:
            return None
        px = (person_bbox.get("x1", 0) + person_bbox.get("x2", 0)) / 2
        py = (person_bbox.get("y1", 0) + person_bbox.get("y2", 0)) / 2

        best = None
        for eq in equipment:
            b = eq["bounding_box"]
            ex = (b["x1"] + b["x2"]) / 2
            ey = (b["y1"] + b["y2"]) / 2
            dist = ((px - ex) ** 2 + (py - ey) ** 2) ** 0.5
            if best is None or dist < best[0]:
                best = (dist, eq)
        return best
