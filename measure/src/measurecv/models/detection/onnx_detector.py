"""RT-DETR via ONNX Runtime.

Two export conventions exist in the wild and both are handled:

* **Post-processed export** (the official RT-DETR ``export_onnx.py``) emits
  ``labels``, ``boxes``, ``scores`` with boxes already in absolute ``xyxy``
  pixels for a fixed ``orig_target_sizes`` input.
* **Raw export** (``optimum``/``torch.onnx`` on the HF model) emits ``logits``
  and ``pred_boxes``, with boxes as normalised ``cxcywh``.

Detecting which one we have from the output shapes -- rather than requiring the
operator to declare it -- avoids a class of silent misconfiguration where boxes
land in the wrong coordinate space and every measurement is wrong without any
error being raised.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.core.config import DetectionConfig
from measurecv.core.device import DeviceContext
from measurecv.core.exceptions import ModelLoadError
from measurecv.core.logging import get_logger
from measurecv.core.types import BoundingBox, Detection
from measurecv.models.base import Detector
from measurecv.models.onnx_runtime import create_session

log = get_logger(__name__)

__all__ = ["OnnxDetector"]

#: RT-DETR's default export resolution.
_DEFAULT_INPUT = (640, 640)


class OnnxDetector(Detector):
    """RT-DETR exported to ONNX."""

    def __init__(self, config: DetectionConfig, device: DeviceContext | None = None) -> None:
        super().__init__(device)
        if config.onnx_path is None:
            raise ModelLoadError("detection.onnx_path must be set for the ONNX detection backend")
        self._config = config
        self._session: Any = None
        self._input_name = ""
        self._size_input: str | None = None
        self._input_hw: tuple[int, int] = _DEFAULT_INPUT
        self._output_names: list[str] = []
        self._labels: dict[int, str] = {}

    @property
    def name(self) -> str:
        return f"rtdetr-onnx:{self._config.onnx_path}"

    def _load(self) -> None:
        assert self._config.onnx_path is not None
        self._session = create_session(self._config.onnx_path, self._device)

        inputs = self._session.get_inputs()
        self._input_name = inputs[0].name
        shape = inputs[0].shape
        # Static exports declare concrete spatial dims; dynamic ones use
        # strings, in which case the export's default resolution is used.
        if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
            self._input_hw = (int(shape[2]), int(shape[3]))

        for extra in inputs[1:]:
            if "size" in extra.name.lower():
                self._size_input = extra.name

        self._output_names = [o.name for o in self._session.get_outputs()]
        self._labels = _coco_labels()

    def _unload(self) -> None:
        self._session = None

    def detect(self, image: NDArray[np.uint8]) -> list[Detection]:
        self.ensure_loaded()
        height, width = image.shape[:2]
        target_h, target_w = self._input_hw

        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        tensor = resized.astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1))[None, ...]

        feeds: dict[str, NDArray[Any]] = {self._input_name: tensor}
        if self._size_input is not None:
            feeds[self._size_input] = np.array([[width, height]], dtype=np.int64)

        outputs = self._session.run(None, feeds)
        boxes, scores, labels = self._decode(outputs, (width, height))

        cfg = self._config
        allowed = {c.lower() for c in cfg.class_whitelist} if cfg.class_whitelist else None

        order = np.argsort(scores)[::-1]
        detections: list[Detection] = []
        for idx in order:
            score = float(scores[idx])
            if score < cfg.score_threshold or len(detections) >= cfg.max_detections:
                break
            label_id = int(labels[idx])
            label = self._labels.get(label_id, f"class_{label_id}")
            if allowed is not None and label.lower() not in allowed:
                continue

            x1, y1, x2, y2 = (float(v) for v in boxes[idx])
            box = BoundingBox(
                max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)
            ).clip(width, height)
            if box.area < cfg.min_box_area_px or box.width < 2 or box.height < 2:
                continue
            detections.append(Detection(bbox=box, score=score, label_id=label_id, label=label))
        return detections

    def _decode(
        self, outputs: list[NDArray[Any]], size: tuple[int, int]
    ) -> tuple[NDArray[np.float32], NDArray[np.float32], NDArray[np.int64]]:
        """Normalise either export convention to absolute xyxy + scores + labels."""
        width, height = size
        named = dict(zip(self._output_names, outputs, strict=False))

        if {"labels", "boxes", "scores"} <= set(named):
            return (
                np.asarray(named["boxes"], dtype=np.float32).reshape(-1, 4),
                np.asarray(named["scores"], dtype=np.float32).reshape(-1),
                np.asarray(named["labels"], dtype=np.int64).reshape(-1),
            )

        logits = np.asarray(outputs[0], dtype=np.float32)
        raw_boxes = np.asarray(outputs[1], dtype=np.float32)
        if logits.ndim == 3:
            logits, raw_boxes = logits[0], raw_boxes[0]

        # RT-DETR uses focal loss, so class scores are independent sigmoids
        # rather than a softmax over classes -- taking a softmax here would
        # systematically distort the scores and break the threshold.
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        labels = probabilities.argmax(axis=-1).astype(np.int64)
        scores = probabilities.max(axis=-1).astype(np.float32)

        cx, cy, bw, bh = raw_boxes[:, 0], raw_boxes[:, 1], raw_boxes[:, 2], raw_boxes[:, 3]
        boxes = np.stack(
            [
                (cx - bw / 2) * width,
                (cy - bh / 2) * height,
                (cx + bw / 2) * width,
                (cy + bh / 2) * height,
            ],
            axis=-1,
        ).astype(np.float32)
        return boxes, scores, labels

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "onnx_path": str(self._config.onnx_path),
            "input_size": list(self._input_hw),
        }


def _coco_labels() -> dict[int, str]:
    """COCO-80 class names in the order RT-DETR exports them."""
    names = [
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "airplane",
        "bus",
        "train",
        "truck",
        "boat",
        "traffic light",
        "fire hydrant",
        "stop sign",
        "parking meter",
        "bench",
        "bird",
        "cat",
        "dog",
        "horse",
        "sheep",
        "cow",
        "elephant",
        "bear",
        "zebra",
        "giraffe",
        "backpack",
        "umbrella",
        "handbag",
        "tie",
        "suitcase",
        "frisbee",
        "skis",
        "snowboard",
        "sports ball",
        "kite",
        "baseball bat",
        "baseball glove",
        "skateboard",
        "surfboard",
        "tennis racket",
        "bottle",
        "wine glass",
        "cup",
        "fork",
        "knife",
        "spoon",
        "bowl",
        "banana",
        "apple",
        "sandwich",
        "orange",
        "broccoli",
        "carrot",
        "hot dog",
        "pizza",
        "donut",
        "cake",
        "chair",
        "couch",
        "potted plant",
        "bed",
        "dining table",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "scissors",
        "teddy bear",
        "hair drier",
        "toothbrush",
    ]
    return dict(enumerate(names))
