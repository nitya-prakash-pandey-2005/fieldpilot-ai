import os
import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()
MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "yolo11n-seg.pt")

class VisionPipeline:
    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO
            # This will auto-download the model if it doesn't exist locally
            self.model = YOLO(MODEL_PATH)
        except ImportError:
            print("Ultralytics not installed. VisionPipeline is running in mock mode.")
        except Exception as e:
            print(f"Failed to load YOLO model from {MODEL_PATH}: {e}")

    def analyze_frame(self, image_path: str):
        if not self.model:
            return self._mock_response()

        try:
            # Run inference
            results = self.model(image_path)
            
            assets_detected = []
            for result in results:
                boxes = result.boxes
                masks = result.masks
                
                if boxes is not None:
                    for i in range(len(boxes)):
                        box = boxes[i]
                        cls_id = int(box.cls[0].item())
                        confidence = float(box.conf[0].item())
                        coords = box.xyxy[0].tolist()  # [x1, y1, x2, y2]
                        class_name = result.names[cls_id]
                        
                        asset = {
                            "asset_id": f"asset_{i}",
                            "asset_type": class_name,
                            "confidence": confidence,
                            "bounding_box": {
                                "x1": coords[0], "y1": coords[1],
                                "x2": coords[2], "y2": coords[3]
                            },
                            "segmentation_mask": None
                        }
                        
                        # Add mask if available (yolo11n-seg.pt)
                        # TODO: SAM2 production integration stub
                        # If a mask is needed and SAM2 is enabled, we would run SAM2 here using the YOLO bounding box as a prompt.
                        if masks is not None and i < len(masks.data):
                            # In production, we'd base64 encode or compress the mask for API transmission
                            asset["segmentation_mask"] = "mask_data_stub"
                            
                        assets_detected.append(asset)
            
            # TODO: GroundingDINO integration stub
            # If certain required assets weren't found by YOLO, we would query GroundingDINO here.
            
            return {
                "assets_detected": assets_detected,
                "scene_context": "auto_detected_scene",
                "status": "success"
            }
            
        except Exception as e:
            print(f"Inference error: {e}")
            return self._mock_response()

    def _mock_response(self):
        return {
            "status": "mock",
            "assets_detected": [
                {
                    "asset_id": "mock_rebar_1",
                    "asset_type": "rebar",
                    "confidence": 0.95,
                    "bounding_box": {"x1": 100, "y1": 150, "x2": 200, "y2": 250},
                    "segmentation_mask": None
                }
            ]
        }
