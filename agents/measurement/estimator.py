import os
import cv2
import numpy as np
from dotenv import load_dotenv
import math

load_dotenv()
DEPTH_MODEL = os.getenv("DEPTH_BACKEND", "aruco")

class MeasurementEngine:
    def __init__(self):
        # Using 4x4 dictionary for robust fast detection (common in construction)
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.aruco_params)

    def estimate_measurements(self, image_path: str, reference_length_mm: float = None):
        """
        Estimates real-world dimensions using ArUco markers or depth models.
        """
        image = cv2.imread(image_path)
        if image is None:
            return {"status": "error", "message": "Failed to read image"}

        if DEPTH_MODEL == "aruco" or reference_length_mm is None:
            return self._measure_with_aruco(image)
        else:
            # TODO: depth_anything or metric3d production integration stub
            # This would initialize the monocular depth pipeline
            print(f"Depth model {DEPTH_MODEL} selected but not implemented in MVP. Falling back to ArUco.")
            return self._measure_with_aruco(image)

    def _measure_with_aruco(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        corners, ids, rejected = self.detector.detectMarkers(gray)
        
        if not corners:
            return {
                "status": "failed",
                "message": "No ArUco markers found in frame for calibration. Provide a known reference object."
            }

        # Assume standard marker size of 100mm (0.1m)
        KNOWN_MARKER_SIZE_MM = 100.0
        
        # Calculate pixel to mm ratio based on the first detected marker
        # We take the perimeter of the marker in pixels and divide by 400mm (4 sides * 100mm)
        marker_corners = corners[0][0]
        perimeter = cv2.arcLength(marker_corners, True)
        pixel_to_mm_ratio = KNOWN_MARKER_SIZE_MM / (perimeter / 4.0)
        
        # In a real scenario, we'd take the coordinates of the two assets detected by Agent 1
        # Here we mock measuring the distance between the center of the image and the marker
        img_h, img_w = image.shape[:2]
        center_x, center_y = img_w / 2, img_h / 2
        
        # Marker center
        m_cx = np.mean(marker_corners[:, 0])
        m_cy = np.mean(marker_corners[:, 1])
        
        distance_px = math.sqrt((center_x - m_cx)**2 + (center_y - m_cy)**2)
        distance_mm = distance_px * pixel_to_mm_ratio
        
        return {
            "status": "success",
            "calibration_method": "aruco_4x4",
            "pixel_to_mm_ratio": round(pixel_to_mm_ratio, 4),
            "measurements": [
                {
                    "type": "spacing",
                    "description": "Distance from camera center to marker",
                    "value": round(distance_mm, 2),
                    "unit": "mm",
                    "confidence": 0.98
                }
            ]
        }
