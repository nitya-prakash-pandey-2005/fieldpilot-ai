"""Deterministic stand-in backends.

These are **test doubles, not fallbacks**. They exist so that the pipeline,
API, CLI, tracking, export and visualisation layers can be exercised end to end
without a GPU, network access, or three gigabytes of weights -- which is what
makes the test-suite fast enough to run on every commit and lets CI verify the
plumbing that surrounds the models.

They are never selected implicitly. A misconfigured deployment fails loudly
with :class:`~measurecv.core.exceptions.ModelLoadError` rather than silently
degrading to fake measurements, because a plausible-looking wrong number is far
more dangerous than an error.

To keep end-to-end tests meaningful the three backends render a *geometrically
consistent* scene: objects are billboards standing on a real ground plane, and
the depth they are given is exactly the depth implied by where their base
contacts that plane. A test can therefore compute the expected metric size
analytically and assert the pipeline recovers it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.device import DeviceContext
from measurecv.core.types import BoundingBox, DepthMap, Detection, InstanceMask
from measurecv.models.base import DepthEstimator, Detector, Segmenter

__all__ = [
    "SYNTHETIC_CAMERA_HEIGHT_M",
    "SyntheticDepthEstimator",
    "SyntheticDetector",
    "SyntheticSegmenter",
    "foreground_mask",
    "ground_depth",
]

#: Camera height above the synthetic ground plane, metres.
SYNTHETIC_CAMERA_HEIGHT_M = 1.40


def foreground_mask(image: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Everything that differs from the modal background colour.

    All three synthetic backends derive their view of the scene from this one
    function, which is what keeps detections, masks and depth mutually
    consistent.
    """
    if image.ndim == 2:
        image = np.stack([image] * 3, axis=-1)
    flat = image.reshape(-1, image.shape[-1])
    # Quantise before taking the mode so that near-identical background pixels
    # (JPEG noise, gradients) collapse to one value.
    quantised = (flat // 16).astype(np.int32)
    codes = quantised[:, 0] * 4096 + quantised[:, 1] * 64 + quantised[:, 2]
    values, counts = np.unique(codes, return_counts=True)
    background = values[int(np.argmax(counts))]
    return (codes != background).reshape(image.shape[:2])


def ground_depth(
    intrinsics: CameraIntrinsics, camera_height: float = SYNTHETIC_CAMERA_HEIGHT_M
) -> NDArray[np.float32]:
    """Depth of a level ground plane seen by a camera at ``camera_height``.

    With no pitch or roll, a ground point projects to row ``v`` where
    ``(v - cy) * Z / fy = camera_height``, so ``Z = fy * h / (v - cy)``. Rows
    at or above the horizon (``v <= cy``) never intersect the plane.
    """
    h, w = intrinsics.height, intrinsics.width
    rows = np.arange(h, dtype=np.float32)[:, None]
    denominator = rows - intrinsics.cy
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(denominator > 0.5, intrinsics.fy * camera_height / denominator, 0.0)
    return np.repeat(z.astype(np.float32), w, axis=1)


class SyntheticDetector(Detector):
    """Finds connected foreground regions and reports them as detections."""

    def __init__(
        self,
        device: DeviceContext | None = None,
        *,
        min_area_px: int = 200,
        label: str = "object",
    ) -> None:
        super().__init__(device)
        self._min_area = min_area_px
        self._label = label

    @property
    def name(self) -> str:
        return "synthetic:detector"

    def _load(self) -> None:
        return

    def detect(self, image: NDArray[np.uint8]) -> list[Detection]:
        self.ensure_loaded()
        mask = foreground_mask(image)
        if not mask.any():
            return []

        count, _labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8
        )
        detections: list[Detection] = []
        height, width = mask.shape
        for label_id in range(1, count):
            area = int(stats[label_id, cv2.CC_STAT_AREA])
            if area < self._min_area:
                continue
            x = int(stats[label_id, cv2.CC_STAT_LEFT])
            y = int(stats[label_id, cv2.CC_STAT_TOP])
            w = int(stats[label_id, cv2.CC_STAT_WIDTH])
            h = int(stats[label_id, cv2.CC_STAT_HEIGHT])
            detections.append(
                Detection(
                    bbox=BoundingBox(float(x), float(y), float(x + w), float(y + h)).clip(
                        width, height
                    ),
                    # Deterministic pseudo-score that rewards larger regions,
                    # so score ordering is stable and reproducible.
                    score=float(min(0.99, 0.55 + area / (mask.size * 2.0))),
                    label_id=1,
                    label=self._label,
                )
            )
        detections.sort(key=lambda d: d.score, reverse=True)
        return detections


class SyntheticSegmenter(Segmenter):
    """Returns the foreground pixels lying inside each prompt box."""

    def __init__(self, device: DeviceContext | None = None) -> None:
        super().__init__(device)

    @property
    def name(self) -> str:
        return "synthetic:segmenter"

    def _load(self) -> None:
        return

    def segment(
        self,
        image: NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        *,
        points: Sequence[tuple[float, float]] | None = None,
    ) -> list[InstanceMask]:
        self.ensure_loaded()
        foreground = foreground_mask(image)
        height, width = foreground.shape

        masks: list[InstanceMask] = []
        for box in boxes:
            clipped = box.clip(width, height)
            window = np.zeros_like(foreground)
            x1, y1 = int(clipped.x1), int(clipped.y1)
            x2, y2 = int(np.ceil(clipped.x2)), int(np.ceil(clipped.y2))
            window[y1:y2, x1:x2] = True
            masks.append(InstanceMask(mask=foreground & window, iou_score=0.95, stability=0.95))
        return masks


class SyntheticDepthEstimator(DepthEstimator):
    """Renders a ground plane with foreground objects standing on it.

    Each object is a fronto-parallel billboard placed at the depth its base row
    implies on the ground plane, so the scene is metrically self-consistent:
    an object whose base sits at row ``v_b`` and whose top sits at row ``v_t``
    has a true height of ``(v_b - v_t) * Z / fy`` metres, which the measurement
    engine should recover.
    """

    def __init__(
        self,
        device: DeviceContext | None = None,
        *,
        camera_height: float = SYNTHETIC_CAMERA_HEIGHT_M,
        background_depth: float = 25.0,
        scale_uncertainty: float = 0.05,
    ) -> None:
        super().__init__(device)
        self._camera_height = camera_height
        self._background_depth = background_depth
        self._scale_uncertainty = scale_uncertainty

    @property
    def name(self) -> str:
        return "synthetic:depth"

    def _load(self) -> None:
        return

    def estimate(self, image: NDArray[np.uint8], intrinsics: CameraIntrinsics) -> DepthMap:
        self.ensure_loaded()
        h, w = image.shape[:2]
        if (intrinsics.width, intrinsics.height) != (w, h):
            intrinsics = intrinsics.scaled(w, h)

        depth = ground_depth(intrinsics, self._camera_height)
        # Above the horizon and beyond the plane's useful range, fall back to a
        # far constant so the map has no invalid holes.
        depth[depth <= 0.0] = self._background_depth
        depth = np.minimum(depth, self._background_depth)

        foreground = foreground_mask(image)
        if foreground.any():
            count, labels, stats, _ = cv2.connectedComponentsWithStats(
                foreground.astype(np.uint8), connectivity=8
            )
            for label_id in range(1, count):
                region = labels == label_id
                base_row = int(stats[label_id, cv2.CC_STAT_TOP]) + int(
                    stats[label_id, cv2.CC_STAT_HEIGHT]
                )
                base_row = min(base_row, h - 1)
                denominator = base_row - intrinsics.cy
                if denominator <= 0.5:
                    continue  # object base is above the horizon; leave as background
                z = float(intrinsics.fy * self._camera_height / denominator)
                depth[region] = np.float32(min(z, self._background_depth))

        return DepthMap(
            depth=depth.astype(np.float32),
            confidence=None,
            scale_uncertainty=self._scale_uncertainty,
        )

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "camera_height_m": self._camera_height,
            "synthetic": True,
        }
