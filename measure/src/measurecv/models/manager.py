"""Model lifecycle and GPU access control.

Two responsibilities:

**Construction.** Maps configuration to concrete backends. This is the only
place in the codebase that knows which backend classes exist, so adding one
(an ONNX detector, a TensorRT depth model) touches exactly this file.

**Serialisation of GPU work.** A web server receives concurrent requests, but a
single GPU does not benefit from running several models at once -- the kernels
interleave, peak memory multiplies, and both requests finish later than if they
had queued. :meth:`ModelManager.inference_slot` enforces a bounded number of
concurrent inference sessions so throughput degrades gracefully into queueing
instead of catastrophically into an out-of-memory error.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from measurecv.core.config import AppConfig
from measurecv.core.device import DeviceContext, resolve_device
from measurecv.core.exceptions import ConfigurationError
from measurecv.core.logging import get_logger
from measurecv.models.base import DepthEstimator, Detector, Segmenter

log = get_logger(__name__)

__all__ = ["ModelManager"]


class ModelManager:
    """Owns the three models and mediates access to them."""

    def __init__(self, config: AppConfig, device: DeviceContext | None = None) -> None:
        self._config = config
        self._device = device or resolve_device(config.runtime.device, config.runtime.precision)
        self._semaphore = threading.BoundedSemaphore(config.api.max_concurrent_inferences)

        self._detector: Detector | None = None
        self._segmenter: Segmenter | None = None
        self._depth: DepthEstimator | None = None
        self._build_lock = threading.Lock()

    @property
    def device(self) -> DeviceContext:
        return self._device

    # -- construction ------------------------------------------------------
    @property
    def detector(self) -> Detector:
        if self._detector is None:
            with self._build_lock:
                if self._detector is None:
                    self._detector = self._build_detector()
        return self._detector

    @property
    def segmenter(self) -> Segmenter:
        if self._segmenter is None:
            with self._build_lock:
                if self._segmenter is None:
                    self._segmenter = self._build_segmenter()
        return self._segmenter

    @property
    def depth_estimator(self) -> DepthEstimator:
        if self._depth is None:
            with self._build_lock:
                if self._depth is None:
                    self._depth = self._build_depth()
        return self._depth

    def _build_detector(self) -> Detector:
        backend = self._config.detection.backend
        if backend == "transformers":
            from measurecv.models.detection.rtdetr import RTDetrDetector

            return RTDetrDetector(self._config.detection, self._device)
        if backend == "onnx":
            from measurecv.models.detection.onnx_detector import OnnxDetector

            return OnnxDetector(self._config.detection, self._device)
        if backend == "synthetic":
            from measurecv.models.synthetic import SyntheticDetector

            log.warning("synthetic_detector_active", impact="measurements are not real")
            return SyntheticDetector(self._device)
        raise ConfigurationError(f"unknown detection backend: {backend}")

    def _build_segmenter(self) -> Segmenter:
        backend = self._config.segmentation.backend
        if backend == "transformers":
            from measurecv.models.segmentation.sam2 import Sam2Segmenter

            return Sam2Segmenter(self._config.segmentation, self._device)
        if backend == "synthetic":
            from measurecv.models.synthetic import SyntheticSegmenter

            log.warning("synthetic_segmenter_active", impact="measurements are not real")
            return SyntheticSegmenter(self._device)
        raise ConfigurationError(f"unknown segmentation backend: {backend}")

    def _build_depth(self) -> DepthEstimator:
        backend = self._config.depth.backend
        if backend == "torch_hub":
            from measurecv.models.depth.metric3d import Metric3DDepthEstimator

            return Metric3DDepthEstimator(self._config.depth, self._device)
        if backend == "onnx":
            from measurecv.models.depth.onnx_depth import OnnxDepthEstimator

            return OnnxDepthEstimator(self._config.depth, self._device)
        if backend == "synthetic":
            from measurecv.models.synthetic import SyntheticDepthEstimator

            log.warning("synthetic_depth_active", impact="measurements are not real")
            return SyntheticDepthEstimator(
                self._device, scale_uncertainty=self._config.depth.scale_uncertainty
            )
        raise ConfigurationError(f"unknown depth backend: {backend}")

    # -- lifecycle ---------------------------------------------------------
    def load_all(self) -> None:
        """Eagerly load every model. Called at server startup so readiness
        genuinely means ready.
        """
        self.detector.ensure_loaded()
        self.segmenter.ensure_loaded()
        self.depth_estimator.ensure_loaded()

    def warmup(self, size: tuple[int, int] = (480, 640)) -> None:
        """Run one dummy pass through each model."""
        if not self._config.runtime.warmup:
            return
        log.info("warmup_start", size=size)
        self.detector.warmup(size)
        self.segmenter.warmup(size)
        self.depth_estimator.warmup(size)
        log.info("warmup_complete")

    def release_all(self) -> None:
        for model in (self._detector, self._segmenter, self._depth):
            if model is not None:
                model.release()

    @contextmanager
    def inference_slot(self) -> Iterator[None]:
        """Bound concurrent GPU work. Blocks when the pool is exhausted."""
        self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()

    def info(self) -> dict[str, Any]:
        """Status of every model, without forcing construction."""
        return {
            "device": self._device.to_dict(),
            "detector": self._detector.info() if self._detector else {"loaded": False},
            "segmenter": self._segmenter.info() if self._segmenter else {"loaded": False},
            "depth": self._depth.info() if self._depth else {"loaded": False},
            "backends": {
                "detection": self._config.detection.backend,
                "segmentation": self._config.segmentation.backend,
                "depth": self._config.depth.backend,
            },
        }
