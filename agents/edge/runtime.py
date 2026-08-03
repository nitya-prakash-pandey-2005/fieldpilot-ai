"""
Edge inference runtime — on-device hazard detection for the pocket node.

The writeup's offline claim: "the pocketed smartphone processes critical safety
hazards locally via its Neural Processing Unit... when the worker walks back
into a WiFi zone, the app batch-syncs the cached incidents". This is the
inference half of that. The store-and-forward half already exists in
scripts/offline_queue.py.

Why a separate runtime rather than reusing agents/vision/detector.py: that
pipeline loads Ultralytics + PyTorch, which is ~2 GB of dependencies and cannot
run on a phone. This is ONNX Runtime only — the same runtime that ships as
onnxruntime-react-native, onnxruntime-android and onnxruntime-objc — with
hand-written pre/post-processing so the identical code path runs on a laptop, a
Jetson, and a phone NPU.

ACCELERATION. ONNX Runtime dispatches to whatever execution provider the device
offers, in the order given. On a phone that is NNAPI (Android NN HAL, which
routes to the Snapdragon Hexagon NPU or equivalent), CoreML (Apple Neural
Engine), or QNN (direct Qualcomm). Selection happens at load time from what is
actually registered, so the same build degrades to CPU on hardware without an
NPU instead of failing.

A caveat worth stating plainly: provider *selection* is implemented and tested,
but NNAPI/CoreML/QNN cannot be exercised on a Windows development box — those
providers only exist in the mobile builds of onnxruntime. What is verified here
is the CPU path plus the fallback logic. Benchmark on the target device before
quoting NPU latency.

CORRECTNESS. Preprocessing must match training exactly. Ultralytics letterboxes
to a square with grey (114,114,114) padding, scales to 0-1, converts BGR->RGB and
HWC->CHW. Getting any of that subtly wrong does not throw — it silently degrades
accuracy in a way that looks like a bad model. The letterbox parameters are kept
so detections can be mapped back to original-image coordinates.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

DEFAULT_MODEL = os.getenv("EDGE_MODEL_PATH", "models/weights/yolo11n-pose-int8.onnx")
DEFAULT_INPUT_SIZE = int(os.getenv("EDGE_INPUT_SIZE", "640"))
DEFAULT_CONF = float(os.getenv("EDGE_CONF_THRESHOLD", "0.35"))
DEFAULT_IOU = float(os.getenv("EDGE_IOU_THRESHOLD", "0.45"))

# Preference order. The first that is actually registered wins.
PROVIDER_PREFERENCE = [
    "QNNExecutionProvider",        # Qualcomm Hexagon NPU, direct
    "NnapiExecutionProvider",      # Android NN HAL -> whatever NPU/DSP/GPU exists
    "CoreMLExecutionProvider",     # Apple Neural Engine
    "TensorrtExecutionProvider",   # Jetson / discrete NVIDIA
    "CUDAExecutionProvider",
    "DmlExecutionProvider",        # DirectML, Windows GPU
    "XnnpackExecutionProvider",    # optimised ARM CPU — still far better than generic
    "CPUExecutionProvider",
]

# COCO keypoint pairs, for drawing a skeleton on-device.
SKELETON = [
    (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16),
]

# Indices into the 17 COCO keypoints.
KP_NOSE, KP_L_SHOULDER, KP_R_SHOULDER = 0, 5, 6
KP_L_HIP, KP_R_HIP = 11, 12
KP_L_ANKLE, KP_R_ANKLE = 15, 16


@dataclass
class EdgeDetection:
    bbox: tuple[float, float, float, float]        # x1, y1, x2, y2 in ORIGINAL image coords
    confidence: float
    keypoints: list[tuple[float, float, float]] = field(default_factory=list)  # x, y, conf

    def as_dict(self) -> dict:
        return {
            "bbox": [round(v, 1) for v in self.bbox],
            "confidence": round(self.confidence, 3),
            "keypoints": [[round(x, 1), round(y, 1), round(c, 3)] for x, y, c in self.keypoints],
        }


@dataclass
class EdgeResult:
    detections: list[EdgeDetection]
    inference_ms: float
    preprocess_ms: float
    postprocess_ms: float
    provider: str
    model: str
    hazards: list[dict] = field(default_factory=list)

    @property
    def total_ms(self) -> float:
        return self.preprocess_ms + self.inference_ms + self.postprocess_ms

    def as_dict(self) -> dict:
        return {
            "person_count": len(self.detections),
            "detections": [d.as_dict() for d in self.detections],
            "hazards": self.hazards,
            "timing_ms": {
                "preprocess": round(self.preprocess_ms, 2),
                "inference": round(self.inference_ms, 2),
                "postprocess": round(self.postprocess_ms, 2),
                "total": round(self.total_ms, 2),
            },
            "provider": self.provider,
            "model": os.path.basename(self.model),
        }


# ---------------------------------------------------------------------------
# pre / post processing
# ---------------------------------------------------------------------------

def letterbox(image: np.ndarray, size: int = 640,
              color: tuple[int, int, int] = (114, 114, 114)):
    """Resize preserving aspect ratio, pad to square.

    Returns (padded_image, scale, pad_x, pad_y). The padding values are needed
    to map detections back — without them every box is offset by the padding,
    which looks like a model that is consistently slightly wrong.
    """
    import cv2

    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    return canvas, scale, pad_x, pad_y


def preprocess(image: np.ndarray, size: int = 640):
    """BGR uint8 HWC -> normalised RGB float32 NCHW, plus letterbox params."""
    import cv2

    padded, scale, pad_x, pad_y = letterbox(image, size)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    tensor = rgb.astype(np.float32) / 255.0
    tensor = np.transpose(tensor, (2, 0, 1))[None]      # HWC -> NCHW
    return np.ascontiguousarray(tensor), scale, pad_x, pad_y


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression on xyxy boxes.

    Written out rather than using cv2.dnn.NMSBoxes so this module depends only
    on numpy at inference time — the mobile port has no OpenCV DNN module.
    """
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[order[1:]] - inter
        iou = np.where(union > 0, inter / union, 0.0)
        order = order[1:][iou <= iou_threshold]
    return keep


# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------

class EdgeDetector:
    """ONNX Runtime pose detector with on-device hazard rules.

    Load once and reuse — session creation costs hundreds of milliseconds and,
    on NNAPI, triggers a model compilation step that is far more expensive still.
    """

    def __init__(self,
                 model_path: str = DEFAULT_MODEL,
                 input_size: int = DEFAULT_INPUT_SIZE,
                 conf_threshold: float = DEFAULT_CONF,
                 iou_threshold: float = DEFAULT_IOU,
                 providers: Optional[list[str]] = None):
        self.model_path = model_path
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.session = None
        self.provider = "none"
        self.load_error: Optional[str] = None
        self._input_name: Optional[str] = None
        self._load(providers)

    def _load(self, providers: Optional[list[str]]) -> None:
        try:
            import onnxruntime as ort
        except ImportError as e:
            self.load_error = f"onnxruntime not installed: {e}"
            return

        if not os.path.exists(self.model_path):
            self.load_error = (f"model not found: {self.model_path}. Export one with "
                               f"python models/training/export_edge.py")
            return

        available = ort.get_available_providers()
        chosen = providers or [p for p in PROVIDER_PREFERENCE if p in available]
        if not chosen:
            chosen = ["CPUExecutionProvider"]

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # A phone has a handful of cores and is also encoding video; letting ORT
        # spawn a thread per core starves the encoder and overheats the device.
        opts.intra_op_num_threads = int(os.getenv("EDGE_THREADS", "2"))

        try:
            self.session = ort.InferenceSession(self.model_path, sess_options=opts,
                                                providers=chosen)
            self.provider = self.session.get_providers()[0]
            self._input_name = self.session.get_inputs()[0].name
        except Exception as e:
            self.load_error = f"could not create session: {e}"

    @property
    def ready(self) -> bool:
        return self.session is not None

    # -- inference ---------------------------------------------------------

    def detect(self, image: np.ndarray) -> EdgeResult:
        if not self.ready:
            return EdgeResult([], 0.0, 0.0, 0.0, "none", self.model_path,
                              hazards=[{"type": "edge_unavailable",
                                        "detail": self.load_error or "not loaded"}])

        t0 = time.perf_counter()
        tensor, scale, pad_x, pad_y = preprocess(image, self.input_size)
        t1 = time.perf_counter()

        outputs = self.session.run(None, {self._input_name: tensor})
        t2 = time.perf_counter()

        detections = self._decode(outputs[0], scale, pad_x, pad_y,
                                  image.shape[1], image.shape[0])
        hazards = self.assess_hazards(detections, image.shape[1], image.shape[0])
        t3 = time.perf_counter()

        return EdgeResult(
            detections=detections,
            preprocess_ms=(t1 - t0) * 1000,
            inference_ms=(t2 - t1) * 1000,
            postprocess_ms=(t3 - t2) * 1000,
            provider=self.provider,
            model=self.model_path,
            hazards=hazards,
        )

    def _decode(self, output: np.ndarray, scale: float, pad_x: int, pad_y: int,
                orig_w: int, orig_h: int) -> list[EdgeDetection]:
        """YOLO11-pose head: [1, 56, 8400] -> detections in original coordinates.

        56 = 4 box (cx, cy, w, h) + 1 objectness + 17 keypoints x (x, y, conf).
        The 8400 anchors come from the 80/40/20 feature-map strides at 640px.
        """
        pred = output[0]                       # (56, 8400)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T                      # -> (8400, 56)

        scores = pred[:, 4]
        keep_mask = scores >= self.conf_threshold
        if not np.any(keep_mask):
            return []
        pred = pred[keep_mask]
        scores = scores[keep_mask]

        cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
        boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)

        keep = nms(boxes, scores, self.iou_threshold)
        if not keep:
            return []

        # Undo the letterbox: subtract padding, then divide by the resize scale.
        # Doing these in the wrong order is the classic source of boxes that are
        # right in the middle of the frame and progressively wrong at the edges.
        def to_orig(x: np.ndarray, y: np.ndarray):
            return ((x - pad_x) / scale, (y - pad_y) / scale)

        results: list[EdgeDetection] = []
        for i in keep:
            bx1, by1 = to_orig(boxes[i, 0], boxes[i, 1])
            bx2, by2 = to_orig(boxes[i, 2], boxes[i, 3])
            bx1, bx2 = float(np.clip(bx1, 0, orig_w)), float(np.clip(bx2, 0, orig_w))
            by1, by2 = float(np.clip(by1, 0, orig_h)), float(np.clip(by2, 0, orig_h))

            kps: list[tuple[float, float, float]] = []
            raw_kp = pred[i, 5:]
            if raw_kp.size >= 51:
                for k in range(17):
                    kx, ky, kc = raw_kp[k * 3], raw_kp[k * 3 + 1], raw_kp[k * 3 + 2]
                    ox, oy = to_orig(kx, ky)
                    kps.append((float(ox), float(oy), float(kc)))

            results.append(EdgeDetection(bbox=(bx1, by1, bx2, by2),
                                         confidence=float(scores[i]),
                                         keypoints=kps))
        return results

    # -- on-device hazard rules -------------------------------------------

    def assess_hazards(self, detections: list[EdgeDetection],
                       frame_w: int, frame_h: int) -> list[dict]:
        """Rules cheap enough to run every frame on a phone.

        Deliberately geometric, not learned: a second model would double the
        power budget, and these are the hazards that must fire with zero network
        latency. Anything needing judgement is left to the cloud agents.
        """
        hazards: list[dict] = []

        for idx, det in enumerate(detections):
            x1, y1, x2, y2 = det.bbox
            bw, bh = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
            kps = det.keypoints

            # --- fall: a standing person's bounding box is taller than wide ---
            aspect = bh / bw
            if aspect < 0.75:
                hazards.append({
                    "type": "possible_fall", "person_index": idx,
                    "severity": "critical",
                    "detail": f"bounding box wider than tall (aspect {aspect:.2f})",
                    "confidence": round(min(0.5 + (0.75 - aspect), 0.95), 2),
                })

            # --- torso orientation, when keypoints are confident enough -------
            if len(kps) >= 17:
                sh = [kps[KP_L_SHOULDER], kps[KP_R_SHOULDER]]
                hp = [kps[KP_L_HIP], kps[KP_R_HIP]]
                if all(p[2] > 0.5 for p in sh + hp):
                    sx = (sh[0][0] + sh[1][0]) / 2
                    sy = (sh[0][1] + sh[1][1]) / 2
                    hx = (hp[0][0] + hp[1][0]) / 2
                    hy = (hp[0][1] + hp[1][1]) / 2
                    # Angle of the shoulder-hip axis from vertical.
                    import math
                    tilt = abs(math.degrees(math.atan2(abs(hx - sx), abs(hy - sy) + 1e-6)))
                    if tilt > 55:
                        hazards.append({
                            "type": "torso_horizontal", "person_index": idx,
                            "severity": "critical",
                            "detail": f"torso {tilt:.0f}deg from vertical",
                            "confidence": 0.8,
                        })

            # --- proximity to frame edge: a worker at the edge of a wide-FOV
            #     capture is often at the edge of a deck or opening. Weak signal
            #     on its own, so it is advisory, never a stop-work.
            if x1 < frame_w * 0.02 or x2 > frame_w * 0.98:
                hazards.append({
                    "type": "near_frame_edge", "person_index": idx,
                    "severity": "low",
                    "detail": "worker at the edge of the captured field of view",
                    "confidence": 0.4,
                })

        return hazards

    # -- introspection -----------------------------------------------------

    def status(self) -> dict:
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            version = ort.__version__
        except ImportError:
            available, version = [], None

        npu = [p for p in available
               if p in ("QNNExecutionProvider", "NnapiExecutionProvider",
                        "CoreMLExecutionProvider")]
        return {
            "ready": self.ready,
            "model": self.model_path,
            "model_size_mb": round(os.path.getsize(self.model_path) / 1e6, 2)
            if os.path.exists(self.model_path) else None,
            "active_provider": self.provider,
            "available_providers": available,
            "npu_providers_present": npu,
            "npu_accelerated": bool(self.provider in npu),
            "onnxruntime_version": version,
            "input_size": self.input_size,
            "threads": int(os.getenv("EDGE_THREADS", "2")),
            "load_error": self.load_error,
            "note": None if npu else
                    "No NPU execution provider is registered in this build of "
                    "onnxruntime — this is the desktop build, which ships CPU only. "
                    "NNAPI/CoreML/QNN appear in onnxruntime-react-native / "
                    "-android / -objc on a real device. Selection logic is the "
                    "same; benchmark on the target hardware before quoting NPU "
                    "latency.",
        }


_detector: Optional[EdgeDetector] = None


def get_detector() -> EdgeDetector:
    """Process-wide singleton — session creation is expensive."""
    global _detector
    if _detector is None:
        _detector = EdgeDetector()
    return _detector
