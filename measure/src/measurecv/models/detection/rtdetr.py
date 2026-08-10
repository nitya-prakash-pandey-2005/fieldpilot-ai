"""RT-DETR object detection backend.

RT-DETR is used rather than a YOLO-family detector for one property that
matters here: it is **NMS-free**. Its one-to-one Hungarian assignment produces
exactly one query per object, so there is no IoU threshold to tune and no
duplicate-suppression stage that can merge two adjacent objects into one.

That matters more for measurement than for plain detection. A duplicate box
means SAM 2 gets prompted twice and the same object is measured twice; a
merged box means SAM 2 receives a prompt spanning two objects and returns a
mask covering both, whose point cloud yields a confidently wrong dimension.
Removing the NMS heuristic removes that whole failure mode.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.core.config import DetectionConfig
from measurecv.core.device import DeviceContext, autocast_context
from measurecv.core.exceptions import ModelLoadError
from measurecv.core.logging import get_logger
from measurecv.core.types import BoundingBox, Detection
from measurecv.models.base import Detector

log = get_logger(__name__)

__all__ = ["RTDetrDetector"]


class RTDetrDetector(Detector):
    """RT-DETR / RT-DETRv2 via HuggingFace ``transformers``."""

    def __init__(self, config: DetectionConfig, device: DeviceContext | None = None) -> None:
        super().__init__(device)
        self._config = config
        self._model: Any = None
        self._processor: Any = None
        self._id2label: dict[int, str] = {}
        self._allowed_ids: set[int] | None = None

    @property
    def name(self) -> str:
        return f"rtdetr:{self._config.model_id}"

    def _load(self) -> None:
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForObjectDetection
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ModelLoadError(
                "RT-DETR needs the 'models' extra: pip install 'measurecv[models]'",
                missing=str(exc),
            ) from exc

        model_id = self._config.model_id
        try:
            self._processor = AutoImageProcessor.from_pretrained(model_id)
            model = AutoModelForObjectDetection.from_pretrained(model_id)
        except Exception as exc:
            raise ModelLoadError(
                f"could not load RT-DETR weights '{model_id}': {exc}",
                model_id=model_id,
            ) from exc

        model.eval()
        model.to(self._device.torch_device)

        if self._device.is_cuda:
            # channels_last suits the convolutional backbone; harmless for the
            # transformer encoder/decoder on top.
            model = model.to(memory_format=torch.channels_last)
            if self._device.dtype_name != "fp32":
                model = model.to(self._device.torch_dtype)

        if self._config.compile_model:
            try:
                model = torch.compile(model, mode="max-autotune", dynamic=True)
                log.info("model_compiled", model=self.name)
            except Exception as exc:  # compile is an optimisation, not a requirement
                log.warning("torch_compile_failed", model=self.name, error=str(exc))

        self._model = model
        raw = getattr(model.config, "id2label", None) or {}
        self._id2label = {int(k): str(v) for k, v in raw.items()}

        if self._config.class_whitelist:
            wanted = {c.lower() for c in self._config.class_whitelist}
            self._allowed_ids = {
                i for i, label in self._id2label.items() if label.lower() in wanted
            }
            missing = wanted - {self._id2label[i].lower() for i in self._allowed_ids}
            if missing:
                log.warning(
                    "unknown_classes_in_whitelist",
                    unknown=sorted(missing),
                    hint="check spelling against the model's COCO label set",
                )

    def _unload(self) -> None:
        self._model = None
        self._processor = None

    def detect(self, image: NDArray[np.uint8]) -> list[Detection]:
        return self.detect_batch([image])[0]

    def detect_batch(self, images: Sequence[NDArray[np.uint8]]) -> list[list[Detection]]:
        """True batched inference -- a large throughput win on GPU."""
        self.ensure_loaded()
        if not images:
            return []

        import torch

        cfg = self._config
        sizes = [(int(img.shape[0]), int(img.shape[1])) for img in images]

        inputs = self._processor(images=list(images), return_tensors="pt")
        inputs = {k: v.to(self._device.torch_device) for k, v in inputs.items()}
        half_precision = self._device.is_cuda and self._device.dtype_name != "fp32"
        if half_precision and "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(self._device.torch_dtype)

        with torch.inference_mode(), autocast_context(self._device):
            outputs = self._model(**inputs)

        target_sizes = torch.tensor(sizes, device=self._device.torch_device)
        results = self._processor.post_process_object_detection(
            outputs, target_sizes=target_sizes, threshold=cfg.score_threshold
        )

        return [
            self._to_detections(result, size) for result, size in zip(results, sizes, strict=True)
        ]

    def _to_detections(self, result: dict[str, Any], size: tuple[int, int]) -> list[Detection]:
        height, width = size
        scores = result["scores"].detach().float().cpu().numpy()
        labels = result["labels"].detach().cpu().numpy()
        boxes = result["boxes"].detach().float().cpu().numpy()

        order = np.argsort(scores)[::-1]
        detections: list[Detection] = []

        for idx in order:
            if len(detections) >= self._config.max_detections:
                break
            label_id = int(labels[idx])
            if self._allowed_ids is not None and label_id not in self._allowed_ids:
                continue

            x1, y1, x2, y2 = (float(v) for v in boxes[idx])
            # The processor can emit coordinates marginally outside the frame;
            # clamp before they reach mask indexing.
            box = BoundingBox(
                max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)
            ).clip(width, height)

            if box.area < self._config.min_box_area_px:
                continue
            if box.width < 2.0 or box.height < 2.0:
                continue

            detections.append(
                Detection(
                    bbox=box,
                    score=float(scores[idx]),
                    label_id=label_id,
                    label=self._id2label.get(label_id, f"class_{label_id}"),
                )
            )

        return detections

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "model_id": self._config.model_id,
            "score_threshold": self._config.score_threshold,
            "num_classes": len(self._id2label),
            "class_whitelist": self._config.class_whitelist,
        }
