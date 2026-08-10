"""Metric3D via ONNX Runtime.

Shares :func:`~measurecv.models.depth.metric3d.preprocess_metric3d` and
:func:`~measurecv.models.depth.metric3d.postprocess_metric3d` with the PyTorch
backend, so the canonical-to-metric conversion has exactly one implementation.
Duplicating that arithmetic across backends would be the obvious way to end up
with two backends that silently disagree about scale.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.config import DepthConfig
from measurecv.core.device import DeviceContext
from measurecv.core.exceptions import DepthEstimationError, ModelLoadError
from measurecv.core.logging import get_logger
from measurecv.core.types import DepthMap
from measurecv.models.base import DepthEstimator
from measurecv.models.depth.metric3d import postprocess_metric3d, preprocess_metric3d
from measurecv.models.onnx_runtime import create_session

log = get_logger(__name__)

__all__ = ["OnnxDepthEstimator"]


class OnnxDepthEstimator(DepthEstimator):
    """Metric3D exported to ONNX."""

    def __init__(self, config: DepthConfig, device: DeviceContext | None = None) -> None:
        super().__init__(device)
        if config.onnx_path is None:
            raise ModelLoadError("depth.onnx_path must be set for the ONNX depth backend")
        self._config = config
        self._session: Any = None
        self._input_name: str = ""

    @property
    def name(self) -> str:
        return f"metric3d-onnx:{self._config.onnx_path}"

    def _load(self) -> None:
        assert self._config.onnx_path is not None
        self._session = create_session(self._config.onnx_path, self._device)
        self._input_name = self._session.get_inputs()[0].name

    def _unload(self) -> None:
        self._session = None

    def estimate(self, image: NDArray[np.uint8], intrinsics: CameraIntrinsics) -> DepthMap:
        self.ensure_loaded()
        cfg = self._config
        h, w = image.shape[:2]
        if (intrinsics.width, intrinsics.height) != (w, h):
            raise DepthEstimationError(
                f"intrinsics are for {intrinsics.width}x{intrinsics.height} "
                f"but the image is {w}x{h}"
            )

        array, scale, pad = preprocess_metric3d(image, cfg.input_size)
        batch = array[None, ...].astype(np.float32)

        outputs = self._session.run(None, {self._input_name: batch})
        depth_canonical = np.asarray(outputs[0], dtype=np.float32).squeeze()
        if depth_canonical.ndim != 2:
            raise DepthEstimationError(
                f"unexpected ONNX depth output shape {depth_canonical.shape}; "
                "expected a single-channel depth map"
            )

        depth = postprocess_metric3d(depth_canonical, pad, (h, w), intrinsics, scale, cfg)

        valid_fraction = float((depth > 0).mean())
        if valid_fraction < 0.2:
            raise DepthEstimationError(
                f"only {valid_fraction:.1%} of the depth map is usable",
                valid_fraction=valid_fraction,
            )

        confidence: NDArray[np.float32] | None = None
        if cfg.use_confidence and len(outputs) > 1:
            raw = np.asarray(outputs[1], dtype=np.float32).squeeze()
            if raw.ndim == 2:
                import cv2

                pad_top, pad_bottom, pad_left, pad_right = pad
                cropped = raw[
                    pad_top : raw.shape[0] - pad_bottom, pad_left : raw.shape[1] - pad_right
                ]
                confidence = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

        return DepthMap(depth=depth, confidence=confidence, scale_uncertainty=cfg.scale_uncertainty)

    def info(self) -> dict[str, Any]:
        return {**super().info(), "onnx_path": str(self._config.onnx_path)}
