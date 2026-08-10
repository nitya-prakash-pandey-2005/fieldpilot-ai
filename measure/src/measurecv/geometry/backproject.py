"""Turning a mask + depth map into a trustworthy metric point cloud.

This is the single most important module for accuracy, and almost all of it is
filtering rather than projection. The projection itself is three lines of
arithmetic; the difficulty is that a naive application of it produces point
clouds contaminated in exactly the way that maximally corrupts extent
estimates.

The three contamination sources, and what we do about them:

1. **Boundary bleed.** Monocular depth networks smooth across object
   silhouettes, so pixels within a few of the mask edge carry a blend of
   foreground and background depth. Those pixels back-project to points
   stretched along the view ray -- and since they sit at the object's outline,
   they land at the extremes of every principal axis. Erosion removes them.

2. **Depth discontinuities inside the mask.** Thin structures, occluders and
   mask leakage create step edges. A relative-gradient test finds them without
   needing an absolute threshold (a 5 cm step matters at 1 m, not at 50 m).

3. **Isolated flyers.** Whatever survives 1 and 2 still contains sparse noise.
   A robust per-mask depth gate (median absolute deviation) removes the bulk,
   and a k-nearest-neighbour statistical filter removes the rest in 3-D, where
   the notion of "isolated" is physically meaningful.

Every filter reports how much it removed, so a caller can see when an object
was measured from 8% of its pixels and treat the result accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.config import MeasurementConfig
from measurecv.core.exceptions import InsufficientDataError
from measurecv.core.logging import get_logger
from measurecv.core.types import DepthMap, InstanceMask, PointCloud

log = get_logger(__name__)

__all__ = [
    "FilterReport",
    "backproject_mask",
    "depth_edge_mask",
    "largest_component",
    "robust_depth_gate",
    "statistical_outlier_filter",
]


@dataclass(slots=True)
class FilterReport:
    """Audit trail of how many pixels/points each stage removed."""

    initial_px: int = 0
    after_component_px: int = 0
    after_erosion_px: int = 0
    after_edge_px: int = 0
    after_depth_gate_px: int = 0
    after_outlier_px: int = 0
    subsampled_to: int = 0
    boundary_shrink_px: float = 0.0
    """Mean inward displacement of the silhouette caused by the *spatial*
    filters (erosion and edge suppression), in pixels.

    This is a bias, not noise: those filters deliberately remove the object's
    outermost pixels, so every lateral extent comes out short by twice this
    value. Because the amount is knowable it is measured here and corrected
    downstream rather than left in the result.

    Estimated as ``removed_area / perimeter``, which is the standard
    small-``r`` morphology relation ``dA ~ P * r``. Deriving it from the actual
    pixels makes it independent of kernel shape and of which filters ended up
    being applied."""
    notes: list[str] = field(default_factory=list)

    @property
    def retention(self) -> float:
        """Fraction of the original mask that survived. Low values mean the
        measurement rests on a small, possibly unrepresentative sample.
        """
        return self.after_outlier_px / self.initial_px if self.initial_px else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_px": self.initial_px,
            "after_component_px": self.after_component_px,
            "after_erosion_px": self.after_erosion_px,
            "after_edge_px": self.after_edge_px,
            "after_depth_gate_px": self.after_depth_gate_px,
            "after_outlier_px": self.after_outlier_px,
            "subsampled_to": self.subsampled_to,
            "boundary_shrink_px": round(self.boundary_shrink_px, 3),
            "retention": round(self.retention, 4),
            "notes": list(self.notes),
        }


def largest_component(mask: NDArray[np.bool_], min_ratio: float = 0.15) -> NDArray[np.bool_]:
    """Keep only the dominant connected blob.

    SAM occasionally returns a mask with satellite fragments (reflections,
    similar nearby objects). Those fragments sit at a different depth and would
    inflate the object's measured extent. Fragments are dropped unless they
    hold at least ``min_ratio`` of the total area, in which case the mask is
    left alone -- a genuinely two-part object (e.g. an occluded chair) should
    not be silently halved.
    """
    if not mask.any():
        return mask
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    if count <= 2:  # background + one component
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    order = np.argsort(areas)[::-1]
    largest = int(order[0]) + 1
    second_ratio = areas[order[1]] / areas[order[0]] if areas.size > 1 else 0.0
    if second_ratio >= min_ratio:
        return mask
    return labels == largest


def depth_edge_mask(
    depth: NDArray[np.float32], threshold: float = 0.06, dilate_px: int = 2
) -> NDArray[np.bool_]:
    """Locate depth discontinuities using a *relative* gradient.

    Using ``|grad Z| / Z`` rather than ``|grad Z|`` makes one threshold valid
    across the whole scene: a step is significant when it is large relative to
    the distance at which it occurs.
    """
    safe = np.where(np.isfinite(depth) & (depth > 0), depth, np.nan).astype(np.float32)
    filled = np.nan_to_num(safe, nan=0.0)
    gx = cv2.Sobel(filled, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(filled, cv2.CV_32F, 0, 1, ksize=3)
    # Sobel with ksize=3 has a gain of 8 relative to a unit finite difference.
    grad = np.sqrt(gx * gx + gy * gy) / 8.0
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = grad / np.maximum(filled, 1e-6)
    edges = np.isfinite(relative) & (relative > threshold)
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1)
        )
        edges = cv2.dilate(edges.astype(np.uint8), kernel).astype(bool)
    return edges


def robust_depth_gate(
    depth_values: NDArray[np.float64], mad_scale: float = 3.0
) -> NDArray[np.bool_]:
    """Median-absolute-deviation gate on the depth samples of one object.

    A mean/std gate would be dragged by the very outliers it is meant to catch;
    the median and MAD have a 50% breakdown point. The 1.4826 factor makes MAD
    a consistent estimator of sigma for normally distributed data, so
    ``mad_scale`` reads as "sigmas".

    Bimodal depth within a mask (background leaking in) shows up as a large
    MAD, and this gate keeps the dominant mode -- the correct behaviour, since
    the dominant mode is the object.
    """
    if depth_values.size == 0:
        return np.zeros(0, dtype=bool)
    median = float(np.median(depth_values))
    mad = float(np.median(np.abs(depth_values - median)))
    if mad <= 1e-9:
        # Degenerate spread (e.g. a synthetic flat surface): accept everything
        # rather than rejecting all but an exact-median pixel.
        return np.ones_like(depth_values, dtype=bool)
    sigma = 1.4826 * mad
    return np.abs(depth_values - median) <= mad_scale * sigma


def estimate_boundary_shrink(
    original: NDArray[np.bool_],
    retained_rows: NDArray[np.int64],
    retained_cols: NDArray[np.int64],
    max_px: float = 12.0,
) -> float:
    """Inward displacement of the silhouette, as an equivalent erosion radius.

    Measured with a distance transform of the *original* mask: if the retained
    pixel set is essentially ``{d > r}`` for the distance-to-background field
    ``d``, then the smallest ``d`` among retained pixels is ``r``. A low
    percentile is used rather than the true minimum so a handful of surviving
    stragglers cannot defeat the estimate.

    This formulation is why every spatial filter is covered automatically --
    erosion, edge suppression, and the border-shaving that the k-NN outlier
    filter performs on planar surfaces all show up as the same displacement,
    with no per-filter bookkeeping and no assumption about kernel shapes.

    Interior removals (a genuine hole punched out by the depth gate) sit at
    large ``d`` and so leave the low tail -- and therefore this estimate --
    untouched, which is the desired behaviour.

    Returns:
        Displacement in pixels, clamped to ``max_px``.
    """
    if retained_rows.size == 0:
        return 0.0
    # distanceTransform needs a border of background around the region, so pad
    # by one pixel to get correct distances for objects touching the frame.
    padded = np.pad(original.astype(np.uint8), 1, mode="constant")
    dist = cv2.distanceTransform(padded, cv2.DIST_L2, 5)[1:-1, 1:-1]
    values = dist[retained_rows, retained_cols]
    if values.size == 0:
        return 0.0
    radius = float(np.percentile(values, 1.0))
    return float(np.clip(radius, 0.0, max_px))


def statistical_outlier_filter(
    points: NDArray[np.float64], k: int = 16, std_ratio: float = 2.0
) -> NDArray[np.bool_]:
    """Remove points whose mean distance to their ``k`` neighbours is unusual.

    This is the standard PCL-style filter. It runs in 3-D rather than in depth
    space so that a point which is depth-plausible but spatially detached (a
    fragment of wall visible through a handle, say) is still caught.
    """
    n = points.shape[0]
    if k <= 0 or n <= k + 1:
        return np.ones(n, dtype=bool)

    tree = cKDTree(points)
    # +1 because the query point is its own nearest neighbour at distance 0.
    distances, _ = tree.query(points, k=k + 1, workers=-1)
    mean_dist = distances[:, 1:].mean(axis=1)

    mu = float(mean_dist.mean())
    sigma = float(mean_dist.std())
    if sigma <= 1e-12:
        return np.ones(n, dtype=bool)
    return mean_dist <= mu + std_ratio * sigma


def backproject_mask(
    instance: InstanceMask,
    depth_map: DepthMap,
    intrinsics: CameraIntrinsics,
    config: MeasurementConfig,
    *,
    image: NDArray[np.uint8] | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[PointCloud, FilterReport]:
    """Produce a filtered metric point cloud for one object.

    Args:
        instance: The SAM 2 mask, at full image resolution.
        depth_map: Metric depth for the same frame.
        intrinsics: Camera model matching the frame size.
        config: Filtering parameters.
        image: Optional RGB, used to colour the cloud for export.
        rng: Seeded generator so subsampling is reproducible.

    Returns:
        The point cloud and a :class:`FilterReport`.

    Raises:
        InsufficientDataError: Fewer than ``config.min_points`` survive. The
            caller is expected to record a warning for this object rather than
            emit an unreliable number.
    """
    mask = instance.mask
    h, w = mask.shape
    if depth_map.shape != (h, w):
        raise ValueError(
            f"mask {mask.shape} and depth {depth_map.shape} disagree; resize before back-projection"
        )
    if (intrinsics.width, intrinsics.height) != (w, h):
        raise ValueError(
            f"intrinsics are for {intrinsics.width}x{intrinsics.height} but the frame is {w}x{h}"
        )

    report = FilterReport(initial_px=int(mask.sum()))
    if report.initial_px == 0:
        raise InsufficientDataError("empty mask")

    work = largest_component(mask)
    report.after_component_px = int(work.sum())
    spatial_before = work

    if config.mask_erode_px > 0:
        ksize = 2 * config.mask_erode_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        eroded = cv2.erode(work.astype(np.uint8), kernel).astype(bool)
        # Thin objects (cables, table legs) can erode to nothing. Falling back
        # to the un-eroded mask keeps a noisier measurement rather than none,
        # and the note tells the confidence model to discount it.
        if eroded.sum() >= max(config.min_points, 0.05 * report.after_component_px):
            work = eroded
        else:
            report.notes.append("erosion_skipped_thin_object")
    report.after_erosion_px = int(work.sum())

    if config.depth_edge_suppression:
        edges = depth_edge_mask(depth_map.depth, config.depth_edge_threshold)
        candidate = work & ~edges
        # Same guard: an object made entirely of depth edges (a wire fence)
        # should still be measurable, just with lower confidence.
        if candidate.sum() >= max(config.min_points, 0.05 * report.after_erosion_px):
            work = candidate
        else:
            report.notes.append("edge_suppression_skipped")
    report.after_edge_px = int(work.sum())

    valid = depth_map.valid()
    work = work & valid
    if not work.any():
        raise InsufficientDataError(
            "no valid depth samples inside the mask",
            mask_px=report.initial_px,
        )

    rows, cols = np.nonzero(work)
    z = depth_map.depth[rows, cols].astype(np.float64)

    keep = robust_depth_gate(z, config.outlier_mad_scale)
    rows, cols, z = rows[keep], cols[keep], z[keep]
    report.after_depth_gate_px = int(rows.size)
    if rows.size < config.min_points:
        raise InsufficientDataError(
            f"only {rows.size} samples survived depth filtering (need {config.min_points})",
            surviving=int(rows.size),
            required=config.min_points,
        )

    points = intrinsics.backproject(cols.astype(np.float64), rows.astype(np.float64), z)

    if config.statistical_outlier_k > 0:
        keep3d = statistical_outlier_filter(
            points, config.statistical_outlier_k, config.statistical_outlier_std
        )
        points = points[keep3d]
        rows, cols = rows[keep3d], cols[keep3d]
    report.after_outlier_px = int(points.shape[0])

    if points.shape[0] < config.min_points:
        raise InsufficientDataError(
            f"only {points.shape[0]} points survived 3-D filtering (need {config.min_points})",
            surviving=int(points.shape[0]),
            required=config.min_points,
        )

    # Measured against the retained pixels, so it captures every spatial filter
    # applied above -- see estimate_boundary_shrink for why this is the right
    # place to do it.
    report.boundary_shrink_px = estimate_boundary_shrink(spatial_before, rows, cols)

    colors = None
    if image is not None and image.shape[:2] == (h, w):
        colors = image[rows, cols].astype(np.uint8)

    cloud = PointCloud(
        points=points,
        colors=colors,
        pixel_index=np.stack([rows, cols], axis=1).astype(np.int64),
    )
    if len(cloud) > config.max_points:
        cloud = cloud.subsample(config.max_points, rng)
    report.subsampled_to = len(cloud)

    if report.retention < 0.25:
        report.notes.append(f"low_retention_{report.retention:.2f}")

    return cloud, report


def backproject_depth_map(
    depth_map: DepthMap,
    intrinsics: CameraIntrinsics,
    *,
    stride: int = 1,
    image: NDArray[np.uint8] | None = None,
    max_points: int | None = None,
) -> PointCloud:
    """Back-project a whole frame -- used for ground-plane fitting and export."""
    valid = depth_map.valid()
    if stride > 1:
        sub = np.zeros_like(valid)
        sub[::stride, ::stride] = True
        valid = valid & sub

    rows, cols = np.nonzero(valid)
    if rows.size == 0:
        return PointCloud(np.zeros((0, 3)))

    z = depth_map.depth[rows, cols].astype(np.float64)
    points = intrinsics.backproject(cols.astype(np.float64), rows.astype(np.float64), z)
    colors = image[rows, cols].astype(np.uint8) if image is not None else None
    cloud = PointCloud(points, colors, np.stack([rows, cols], axis=1).astype(np.int64))
    if max_points is not None and len(cloud) > max_points:
        cloud = cloud.subsample(max_points)
    return cloud
