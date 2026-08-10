"""Model abstractions.

The pipeline talks to three narrow interfaces -- :class:`Detector`,
:class:`Segmenter`, :class:`DepthEstimator` -- and never to a concrete
backend. That is what lets the same pipeline run against PyTorch weights, an
ONNX/TensorRT export, or the deterministic synthetic stand-ins used in tests,
with no branching in the calling code.

Weights load lazily on first use and can be released, so a long-lived server
that only serves calibration requests never pays for a GPU model it does not
need.
"""

from __future__ import annotations

import abc
import threading
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.device import DeviceContext, empty_cache, resolve_device
from measurecv.core.logging import get_logger
from measurecv.core.types import BoundingBox, DepthMap, Detection, InstanceMask

log = get_logger(__name__)

__all__ = ["DepthEstimator", "Detector", "ModelBase", "Segmenter"]


class ModelBase(abc.ABC):
    """Shared lifecycle: lazy load, thread-safe, releasable.

    The lock matters: a FastAPI server can receive concurrent requests, and two
    threads racing to load the same multi-gigabyte checkpoint would double peak
    memory and can corrupt the HuggingFace cache.
    """

    def __init__(self, device: DeviceContext | None = None) -> None:
        self._device = device or resolve_device()
        self._loaded = False
        self._lock = threading.RLock()

    @property
    def device(self) -> DeviceContext:
        return self._device

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable identifier for logs and the /models endpoint."""

    @abc.abstractmethod
    def _load(self) -> None:
        """Backend-specific weight loading. Called at most once."""

    def _unload(self) -> None:
        """Backend-specific teardown. Override when holding GPU state."""

    def ensure_loaded(self) -> None:
        """Load weights if needed. Safe to call from multiple threads."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:  # another thread won the race
                return
            log.info("model_loading", model=self.name, device=self._device.device)
            self._load()
            self._loaded = True
            log.info("model_loaded", model=self.name)

    def release(self) -> None:
        """Free weights and GPU memory."""
        with self._lock:
            if not self._loaded:
                return
            self._unload()
            self._loaded = False
            empty_cache(self._device)
            log.info("model_released", model=self.name)

    def warmup(self, size: tuple[int, int] = (480, 640)) -> None:
        """Run one dummy inference so the first real request is not slow.

        cuDNN autotuning, lazy CUDA context creation and JIT compilation all
        happen on the first forward pass and can add seconds of latency.
        """
        try:
            self.ensure_loaded()
            self._warmup_impl(size)
            log.debug("model_warmed", model=self.name)
        except Exception as exc:  # warmup is best-effort, never fatal
            log.warning("model_warmup_failed", model=self.name, error=str(exc))

    def _warmup_impl(self, size: tuple[int, int]) -> None:
        """Override to perform a representative dummy inference."""

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "loaded": self._loaded,
            "device": self._device.device,
            "dtype": self._device.dtype_name,
        }


class Detector(ModelBase):
    """Object detection: image -> boxes with class labels."""

    @abc.abstractmethod
    def detect(self, image: NDArray[np.uint8]) -> list[Detection]:
        """Detect objects in one RGB image.

        Args:
            image: ``(H, W, 3)`` uint8 RGB.

        Returns:
            Detections in image pixel coordinates, score-sorted descending.
        """

    def detect_batch(self, images: Sequence[NDArray[np.uint8]]) -> list[list[Detection]]:
        """Batched detection. The default loops; backends should override when
        true batching is available -- it is a large win on GPU.
        """
        return [self.detect(image) for image in images]

    def _warmup_impl(self, size: tuple[int, int]) -> None:
        self.detect(np.zeros((*size, 3), dtype=np.uint8))


class Segmenter(ModelBase):
    """Promptable instance segmentation: image + boxes -> masks."""

    @abc.abstractmethod
    def segment(
        self,
        image: NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        *,
        points: Sequence[tuple[float, float]] | None = None,
    ) -> list[InstanceMask]:
        """Segment the objects indicated by ``boxes``.

        Returns:
            One mask per box, index-aligned. Boxes that produce no usable mask
            still yield an entry (an empty mask) so alignment is preserved --
            the caller is relying on positional correspondence.
        """

    def _warmup_impl(self, size: tuple[int, int]) -> None:
        h, w = size
        self.segment(
            np.zeros((h, w, 3), dtype=np.uint8),
            [BoundingBox(w * 0.25, h * 0.25, w * 0.75, h * 0.75)],
        )


class DepthEstimator(ModelBase):
    """Metric depth: image + intrinsics -> depth in metres."""

    @abc.abstractmethod
    def estimate(self, image: NDArray[np.uint8], intrinsics: CameraIntrinsics) -> DepthMap:
        """Estimate metric depth.

        Args:
            image: ``(H, W, 3)`` uint8 RGB.
            intrinsics: Camera model. **Required, not optional** -- a metric
                depth model cannot produce metric output without knowing the
                focal length, and passing the wrong one produces a
                proportionally wrong result rather than an obvious failure.

        Returns:
            A :class:`DepthMap` at the input resolution, in metres.
        """

    def _warmup_impl(self, size: tuple[int, int]) -> None:
        from measurecv.calibration.intrinsics import intrinsics_from_fov

        h, w = size
        self.estimate(np.zeros((h, w, 3), dtype=np.uint8), intrinsics_from_fov(w, h))
