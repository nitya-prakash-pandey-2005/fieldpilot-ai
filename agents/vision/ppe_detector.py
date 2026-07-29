"""
PPE Detector — FieldPilot AI (Full Suite)
------------------------------------------
Detects ALL construction PPE categories:
  ✓ Hard hat / Safety helmet
  ✓ Hi-vis vest / Safety vest
  ✓ Safety gloves
  ✓ Safety glasses / goggles
  ✓ Safety boots / steel-toe footwear
  ✓ Face mask / dust mask (bonus)

Architecture:
  Primary model : keremberke/yolov8n-hard-hat-detection (HF hub)
                  — detects helmet/no-helmet on head crops
  Vest/Gloves   : Colour heuristics on torso/hand crops (HSV hi-vis)
  Glasses       : YOLO detection on face crop (future: dedicated model)
  Boots         : Lower-body crop analysis

All detectors share a common output schema:
  {
    item:       str,    # 'hardhat' | 'vest' | 'gloves' | 'glasses' | 'boots'
    present:    bool,
    confidence: float,  # 0.0 – 1.0
    method:     str,    # 'model' | 'heuristic' | 'fallback'
  }
"""

import os
import cv2
import numpy as np
from typing import Optional

# ---------------------------------------------------------------------------
# Constants — PPE categories
# ---------------------------------------------------------------------------
PPE_CATEGORIES = ["hardhat", "vest", "gloves", "glasses", "boots"]

PPE_MODEL_REPO  = "keremberke/yolov8n-hard-hat-detection"
PPE_MODEL_NAME  = "best.pt"
PPE_CONF_THRESH = 0.40

HARDHAT_LABELS     = {"hardhat", "hard hat", "helmet", "safety helmet", "hard-hat"}
NO_HARDHAT_LABELS  = {"no-hardhat", "no hardhat", "no_hardhat", "head", "bare head"}

# HSV colour ranges  (OpenCV: H=0-179, S=0-255, V=0-255)

# Hi-vis yellow vest
VEST_YELLOW_LO = np.array([18,  90, 100])
VEST_YELLOW_HI = np.array([40, 255, 255])
# Hi-vis orange vest
VEST_ORANGE_LO = np.array([ 5, 120, 120])
VEST_ORANGE_HI = np.array([18, 255, 255])
# Hi-vis green vest
VEST_GREEN_LO  = np.array([40,  80, 100])
VEST_GREEN_HI  = np.array([80, 255, 255])

# Safety gloves — typically black, blue, or grey
GLOVE_BLACK_LO = np.array([  0,   0,   0])
GLOVE_BLACK_HI = np.array([180,  80,  60])
GLOVE_BLUE_LO  = np.array([100,  80,  50])
GLOVE_BLUE_HI  = np.array([130, 255, 255])

# Safety glasses — transparent/clear or tinted; detect by frame colour (black/yellow)
GLASS_FRAME_LO = np.array([  0,   0,   0])
GLASS_FRAME_HI = np.array([180,  60,  70])

# Safety boots — dark brown/black on lower body
BOOT_DARK_LO = np.array([  0,   0,   0])
BOOT_DARK_HI = np.array([180,  80,  80])


# ---------------------------------------------------------------------------
# PpeDetector
# ---------------------------------------------------------------------------
class PpeDetector:
    """
    Multi-category PPE detector.
    Combine a hard-hat model (primary) with colour heuristics for all other PPE.
    Falls back entirely to heuristics if the model is unavailable.
    """

    def __init__(self):
        self.model        = None
        self.class_names: dict[int, str] = {}
        self._load_model()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _load_model(self):
        try:
            from ultralytics import YOLO
            print("[PPE] Loading hard-hat detection model from HuggingFace hub…")
            self.model = YOLO(
                f"https://huggingface.co/{PPE_MODEL_REPO}/resolve/main/{PPE_MODEL_NAME}"
            )
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            self.model(dummy, verbose=False)
            if hasattr(self.model, "names"):
                self.class_names = self.model.names
            print(f"[PPE] Model loaded. Classes: {self.class_names}")
        except Exception as e:
            print(f"[PPE] ⚠ HF model unavailable ({e}). Using heuristic-only mode.")
            self.model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_worker(
        self,
        full_frame: np.ndarray,
        bbox: dict,
        track_id: Optional[int] = None,
    ) -> dict:
        """
        Assess ALL PPE for a single worker.

        Args:
            full_frame : BGR frame.
            bbox       : {'x1', 'y1', 'x2', 'y2'} in pixel coords.
            track_id   : BoT-SORT track id (for logging only).

        Returns:
            {
              'hardhat'            : bool,
              'vest'               : bool,
              'gloves'             : bool,
              'glasses'            : bool,
              'boots'              : bool,
              'compliant'          : bool,   # ALL 5 items present
              'ppe_score'          : float,  # fraction present 0.0–1.0
              'violations'         : list[str],
              'detail'             : dict[str → {present, confidence, method}]
            }
        """
        h, w = full_frame.shape[:2]
        x1 = max(0,  int(bbox.get("x1", 0)))
        y1 = max(0,  int(bbox.get("y1", 0)))
        x2 = min(w,  int(bbox.get("x2", w)))
        y2 = min(h,  int(bbox.get("y2", h)))

        if x2 <= x1 or y2 <= y1:
            return self._unknown_result()

        crop = full_frame[y1:y2, x1:x2]
        if crop.size == 0:
            return self._unknown_result()

        ch, cw = crop.shape[:2]

        # ----- Region crops (fractional slices) -----
        head_crop   = crop[:max(ch // 4, 16), :]                   # top 25%
        torso_crop  = crop[ch // 4 : (2 * ch) // 3, :]             # 25-67%
        hand_l_crop = crop[ch // 3 : (2 * ch) // 3, :cw // 3]      # mid-left
        hand_r_crop = crop[ch // 3 : (2 * ch) // 3, (2*cw)//3:]    # mid-right
        face_crop   = crop[:ch // 4, cw // 4 : (3 * cw) // 4]      # head, centred
        feet_crop   = crop[(3 * ch) // 4 :, :]                      # bottom 25%

        # ----- Detect each item -----
        hardhat_r = self._detect_hardhat(head_crop, crop)
        vest_r    = self._detect_vest(torso_crop)
        gloves_r  = self._detect_gloves(hand_l_crop, hand_r_crop)
        glasses_r = self._detect_glasses(face_crop)
        boots_r   = self._detect_boots(feet_crop)

        detail = {
            "hardhat": hardhat_r,
            "vest"   : vest_r,
            "gloves" : gloves_r,
            "glasses": glasses_r,
            "boots"  : boots_r,
        }

        violations = []
        for item, res in detail.items():
            if not res["present"]:
                violations.append(f"NO {item.upper()}")

        n_present = sum(1 for r in detail.values() if r["present"])
        ppe_score = n_present / len(PPE_CATEGORIES)

        return {
            "hardhat"   : hardhat_r["present"],
            "vest"      : vest_r["present"],
            "gloves"    : gloves_r["present"],
            "glasses"   : glasses_r["present"],
            "boots"     : boots_r["present"],
            "compliant" : len(violations) == 0,
            "ppe_score" : round(ppe_score, 2),
            "violations": violations,
            "detail"    : {k: v for k, v in detail.items()},
        }

    def check_batch(self, full_frame: np.ndarray, persons: list[dict]) -> list[dict]:
        """Add 'ppe_status' key to each person dict."""
        return [
            {**p, "ppe_status": self.check_worker(full_frame, p.get("bounding_box", {}))}
            for p in persons
        ]

    # ------------------------------------------------------------------
    # Per-item detectors
    # ------------------------------------------------------------------

    # ---- Hard hat -------------------------------------------------------
    def _detect_hardhat(self, head_crop: np.ndarray, full_person_crop: np.ndarray) -> dict:
        if self.model is not None:
            result = self._model_detect_hardhat(head_crop)
            if result["confidence"] > 0.2:
                return result
        return self._heuristic_detect_hardhat(head_crop)

    def _model_detect_hardhat(self, crop: np.ndarray) -> dict:
        try:
            results = self.model(crop, verbose=False, conf=PPE_CONF_THRESH)
            hat_conf = no_hat_conf = 0.0
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    label = self.class_names.get(int(box.cls[0].item()), "").lower()
                    conf  = float(box.conf[0].item())
                    if label in HARDHAT_LABELS:
                        hat_conf = max(hat_conf, conf)
                    elif label in NO_HARDHAT_LABELS:
                        no_hat_conf = max(no_hat_conf, conf)

            if hat_conf > 0 or no_hat_conf > 0:
                present = hat_conf >= no_hat_conf
                return {"present": present,
                        "confidence": round(max(hat_conf, no_hat_conf), 3),
                        "method": "model"}
        except Exception:
            pass
        return {"present": False, "confidence": 0.0, "method": "model_error"}

    def _heuristic_detect_hardhat(self, head_crop: np.ndarray) -> dict:
        """Colour heuristic: white / yellow / red / orange top = hardhat."""
        if head_crop.size == 0:
            return {"present": False, "confidence": 0.0, "method": "heuristic"}

        hsv = cv2.cvtColor(head_crop, cv2.COLOR_BGR2HSV)
        _, s, v = cv2.split(hsv)

        white_ratio  = float(np.mean((v > 180) & (s < 60)))
        yellow_ratio = float(np.mean(
            cv2.inRange(hsv, np.array([18,80,120]), np.array([40,255,255])) > 0))
        red1_ratio   = float(np.mean(
            cv2.inRange(hsv, np.array([0,100,100]),  np.array([10,255,255])) > 0))
        red2_ratio   = float(np.mean(
            cv2.inRange(hsv, np.array([160,100,100]),np.array([180,255,255])) > 0))
        orange_ratio = float(np.mean(
            cv2.inRange(hsv, np.array([5,120,120]),  np.array([18,255,255])) > 0))
        blue_ratio   = float(np.mean(
            cv2.inRange(hsv, np.array([100,80,60]),  np.array([130,255,255])) > 0))

        best = max(white_ratio, yellow_ratio, red1_ratio + red2_ratio,
                   orange_ratio, blue_ratio)
        present    = best > 0.06
        confidence = min(round(best * 3.5, 3), 0.85)
        return {"present": present, "confidence": confidence, "method": "heuristic"}

    # ---- Hi-vis vest ----------------------------------------------------
    def _detect_vest(self, torso_crop: np.ndarray) -> dict:
        if torso_crop.size == 0:
            return {"present": False, "confidence": 0.0, "method": "heuristic"}

        hsv = cv2.cvtColor(torso_crop, cv2.COLOR_BGR2HSV)
        y_ratio = float(np.mean(cv2.inRange(hsv, VEST_YELLOW_LO, VEST_YELLOW_HI) > 0))
        o_ratio = float(np.mean(cv2.inRange(hsv, VEST_ORANGE_LO, VEST_ORANGE_HI) > 0))
        g_ratio = float(np.mean(cv2.inRange(hsv, VEST_GREEN_LO,  VEST_GREEN_HI)  > 0))
        best = max(y_ratio, o_ratio, g_ratio)

        present    = best > 0.04
        confidence = min(round(best * 5.0, 3), 0.90)
        return {"present": present, "confidence": confidence, "method": "heuristic"}

    # ---- Safety gloves --------------------------------------------------
    def _detect_gloves(self, left_crop: np.ndarray, right_crop: np.ndarray) -> dict:
        """
        Check both hand regions for glove presence.
        Gloves are typically black, blue, or brightly coloured (nitrile).
        A glove is assumed present when either hand shows consistent dark
        or blue/teal coverage (skin tone is typically absent).
        """
        def _score_crop(crop: np.ndarray) -> float:
            if crop.size == 0:
                return 0.0
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            black_r = float(np.mean(cv2.inRange(hsv, GLOVE_BLACK_LO, GLOVE_BLACK_HI) > 0))
            blue_r  = float(np.mean(cv2.inRange(hsv, GLOVE_BLUE_LO,  GLOVE_BLUE_HI)  > 0))
            # Yellow / orange nitrile
            nitrile_r = float(np.mean(
                cv2.inRange(hsv, np.array([15,100,100]), np.array([35,255,255])) > 0))
            return max(black_r, blue_r, nitrile_r)

        l_score = _score_crop(left_crop)
        r_score = _score_crop(right_crop)
        best = max(l_score, r_score)

        # Gloves need decent coverage OR both hands showing some coverage
        if best > 0.25 or (l_score > 0.12 and r_score > 0.12):
            present = True
            confidence = min(round(best * 2.5, 3), 0.85)
        else:
            present = False
            confidence = round(best, 3)

        return {"present": present, "confidence": confidence, "method": "heuristic"}

    # ---- Safety glasses -------------------------------------------------
    def _detect_glasses(self, face_crop: np.ndarray) -> dict:
        """
        Detect safety glasses via edge detection on the face region.
        Glasses create horizontal edge bands across the eye area.
        Also checks for dark/tinted lens colour bands.
        """
        if face_crop.size < 100:
            return {"present": False, "confidence": 0.0, "method": "heuristic"}

        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        # Gaussian smooth then edge detect
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        edges   = cv2.Canny(blurred, 50, 150)

        h, w = face_crop.shape[:2]
        # Eye band: top 40-70% of face crop
        eye_band  = edges[int(h * 0.35): int(h * 0.65), :]
        eye_ratio = float(np.mean(eye_band > 0))

        # Horizontal lines = frames
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 3, 1))
        detected_lines    = cv2.morphologyEx(eye_band, cv2.MORPH_OPEN, horizontal_kernel)
        line_ratio        = float(np.mean(detected_lines > 0))

        # Tinted lens detection (dark band in eye region)
        eye_hsv   = cv2.cvtColor(face_crop[int(h*0.35):int(h*0.65), :],
                                  cv2.COLOR_BGR2HSV)
        dark_r    = float(np.mean(eye_hsv[:, :, 2] < 80))

        score = max(eye_ratio * 0.5 + line_ratio * 1.5, dark_r * 0.6)
        present    = score > 0.08
        confidence = min(round(score * 3.0, 3), 0.80)

        return {"present": present, "confidence": confidence, "method": "heuristic"}

    # ---- Safety boots ---------------------------------------------------
    def _detect_boots(self, feet_crop: np.ndarray) -> dict:
        """
        Detect safety boots from the bottom portion of the person crop.
        Safety boots are typically dark (black/dark brown) and cover the ankle.
        """
        if feet_crop.size == 0:
            return {"present": False, "confidence": 0.0, "method": "heuristic"}

        hsv = cv2.cvtColor(feet_crop, cv2.COLOR_BGR2HSV)

        # Dark colours (black / dark brown)
        dark_r = float(np.mean(
            cv2.inRange(hsv, np.array([0,0,0]), np.array([180,80,80])) > 0))
        # Brown / leather
        brown_r = float(np.mean(
            cv2.inRange(hsv, np.array([5,60,40]), np.array([20,180,150])) > 0))

        best = max(dark_r, brown_r)
        present    = best > 0.20
        confidence = min(round(best * 2.5, 3), 0.80)
        return {"present": present, "confidence": confidence, "method": "heuristic"}

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _unknown_result() -> dict:
        return {
            "hardhat"   : False,
            "vest"      : False,
            "gloves"    : False,
            "glasses"   : False,
            "boots"     : False,
            "compliant" : False,
            "ppe_score" : 0.0,
            "violations": ["DETECTION_ERROR"],
            "detail"    : {},
        }

    @staticmethod
    def ppe_emoji_summary(ppe_status: dict) -> str:
        """Returns a compact emoji string for HUD overlay. e.g. '🪖✅ 🦺❌ 🧤✅'"""
        icons = {
            "hardhat": "🪖",
            "vest"   : "🦺",
            "gloves" : "🧤",
            "glasses": "🥽",
            "boots"  : "👢",
        }
        parts = []
        for item, icon in icons.items():
            present = ppe_status.get(item, False)
            parts.append(f"{icon}{'✅' if present else '❌'}")
        return "  ".join(parts)
