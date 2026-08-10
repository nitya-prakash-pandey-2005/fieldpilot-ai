"""The estimators that turn a point cloud into physical quantities.

Each estimator returns a :class:`~measurecv.core.types.Measured` -- a value with
an uncertainty and a record of the method used. Where several methods exist
(volume especially) the alternatives are computed and reported alongside the
chosen one, because a large disagreement between models is itself the most
useful signal that an object's shape violates the assumptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.config import MeasurementConfig
from measurecv.core.exceptions import DegenerateGeometryError
from measurecv.core.logging import get_logger
from measurecv.core.types import (
    DepthMap,
    Dimensions,
    Measured,
    MeasurementMethod,
    Plane,
    PointCloud,
    Unit,
)
from measurecv.geometry.backproject import FilterReport
from measurecv.geometry.hull import (
    closed_hull_volume,
    ellipsoid_volume,
    mirrored_hull_volume,
    trim_to_core,
)
from measurecv.geometry.obb import OrientedBox, fit_ground_aligned_box, fit_pca_box
from measurecv.geometry.uncertainty import (
    ErrorBudget,
    extent_uncertainty,
    product_uncertainty,
)

log = get_logger(__name__)

#: Confidence ceiling for an object clipped by the frame border. Its
#: measurements are lower bounds, so no combination of other evidence should
#: push it into the range a caller would treat as trustworthy.
_TRUNCATED_CONFIDENCE_CAP = 0.4

__all__ = [
    "MeasurementContext",
    "compute_confidence",
    "estimate_dimensions",
    "estimate_distances",
    "estimate_surface_area",
    "estimate_volume",
    "surface_normals",
]


@dataclass(slots=True)
class MeasurementContext:
    """Per-frame state shared by every estimator."""

    intrinsics: CameraIntrinsics
    depth_map: DepthMap
    config: MeasurementConfig
    budget: ErrorBudget
    plane: Plane | None = None
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0xA11CE))

    @property
    def focal_px(self) -> float:
        """Geometric mean focal length -- the right scalar for isotropic error
        terms when fx and fy differ slightly.
        """
        return math.sqrt(self.intrinsics.fx * self.intrinsics.fy)


# ---------------------------------------------------------------------------
# Boundary bias correction
# ---------------------------------------------------------------------------
def _boundary_compensation_m(report: FilterReport, depth: float, focal_px: float) -> float:
    """Metres of lateral extent lost to the spatial filters, both sides.

    The filters pull the silhouette inward by a measured
    ``boundary_shrink_px`` (see
    :func:`~measurecv.geometry.backproject.estimate_boundary_shrink`). The
    half-pixel term converts between "distance to the outermost retained pixel
    *centre*" and "distance to the true silhouette *edge*", which lies half a
    pixel further out -- without it an unfiltered mask would still come out one
    pixel short.

    Validated on synthetic renders: a 500 mm plate measured 34 mm short before
    this correction and 2 mm short after it.
    """
    shrink = max(0.0, report.boundary_shrink_px - 0.5)
    if shrink <= 0.0 or depth <= 0.0:
        return 0.0
    return 2.0 * shrink * depth / focal_px


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def estimate_dimensions(
    cloud: PointCloud,
    ctx: MeasurementContext,
    report: FilterReport,
) -> tuple[Dimensions, OrientedBox, str]:
    """Fit an oriented box and convert its extents into measured lengths.

    Returns:
        ``(dimensions, box, method_name)``.
    """
    points = cloud.points
    cfg = ctx.config
    depth = float(np.median(points[:, 2]))

    use_ground = ctx.plane is not None and cfg.dimension_method in ("auto", "ground_aligned")
    if cfg.dimension_method == "planar":
        use_ground = False

    box: OrientedBox
    if use_ground and ctx.plane is not None:
        box = fit_ground_aligned_box(points, ctx.plane, cfg.obb_percentile)
        method = MeasurementMethod.GROUND_ALIGNED
    else:
        box = fit_pca_box(points, cfg.obb_percentile)
        method = MeasurementMethod.OBB_3D

    compensation = _boundary_compensation_m(report, depth, ctx.focal_px)

    view = np.array([0.0, 0.0, 1.0])
    measured: list[Measured] = []
    for i in range(3):
        axis = box.axes[i]
        extent = float(box.extents[i])

        # Only the lateral part of an axis is bounded by the silhouette; the
        # axial part is bounded by depth values, which erosion does not move.
        lateral = math.sqrt(max(0.0, 1.0 - float(axis @ view) ** 2))
        corrected = extent + compensation * lateral

        sigma = extent_uncertainty(
            corrected,
            depth=depth,
            axis=axis,
            focal_px=ctx.focal_px,
            n_points=len(cloud),
            budget=ctx.budget,
        )
        # The compensation is itself uncertain -- the shrink estimate is good to
        # roughly half a pixel. Fold that in rather than pretending a bias
        # correction is free.
        if compensation > 0:
            comp_sigma = 0.5 * depth / ctx.focal_px * lateral * 2.0
            sigma = math.hypot(sigma, comp_sigma)

        measured.append(Measured(corrected, sigma, Unit.METRE, method))

    if method is MeasurementMethod.GROUND_ALIGNED:
        # Ground-aligned axes are ordered (footprint-long, footprint-short, up),
        # which is exactly length/width/height.
        length, width, height = measured
    else:
        # PCA axes are ordered by variance. Report the largest extent as
        # length and, lacking a gravity reference, the smallest as height.
        order = np.argsort([m.value for m in measured])[::-1]
        length, width, height = (measured[int(i)] for i in order)
        box = OrientedBox(
            center=box.center,
            axes=box.axes[order],
            extents=box.extents[order],
            footprint_area=box.footprint_area,
            condition=box.condition,
        )

    dims = Dimensions(
        length=length,
        width=width,
        height=height,
        axes=box.axes.copy(),
        origin=box.center.copy(),
    )
    return dims, box, method.value


# ---------------------------------------------------------------------------
# Surface area
# ---------------------------------------------------------------------------
def surface_normals(
    depth: NDArray[np.float32], intrinsics: CameraIntrinsics
) -> NDArray[np.float64]:
    """Per-pixel surface normals from the depth map, via the exact Jacobian.

    For ``P(u,v) = ((u-cx)Z/fx, (v-cy)Z/fy, Z)`` the tangent vectors are the
    partial derivatives of ``P``, and their cross product is the (unnormalised)
    normal. Its magnitude is the metric area of one pixel's surface patch,
    which is why :func:`estimate_surface_area` can integrate it directly
    instead of applying a separate ``1/cos(theta)`` slant correction.
    """
    z = depth.astype(np.float64)
    zu = cv2.Sobel(z, cv2.CV_64F, 1, 0, ksize=3) / 8.0
    zv = cv2.Sobel(z, cv2.CV_64F, 0, 1, ksize=3) / 8.0

    h, w = z.shape
    vv, uu = np.meshgrid(
        np.arange(h, dtype=np.float64), np.arange(w, dtype=np.float64), indexing="ij"
    )
    du = uu - intrinsics.cx
    dv = vv - intrinsics.cy
    fx, fy = intrinsics.fx, intrinsics.fy

    # dP/du
    au = (z + du * zu) / fx
    bu = dv * zu / fy
    cu = zu
    # dP/dv
    av = du * zv / fx
    bv = (z + dv * zv) / fy
    cv_ = zv

    nx = bu * cv_ - cu * bv
    ny = cu * av - au * cv_
    nz = au * bv - bu * av
    return np.stack([nx, ny, nz], axis=-1)


def estimate_surface_area(
    cloud: PointCloud,
    ctx: MeasurementContext,
    report: FilterReport,
) -> Measured:
    """Area of the *visible* surface, by integrating per-pixel patch areas.

    This is the true slanted area, not the frontal projection: a surface tilted
    45 degrees away from the camera correctly reports ~1.41x the area its
    silhouette would suggest.

    Note that this is the area actually seen. For a closed object the total
    surface is larger; :func:`estimate_volume` documents the analogous point
    for volume.
    """
    if cloud.pixel_index is None or len(cloud) == 0:
        return Measured(0.0, 0.0, Unit.SQUARE_METRE, MeasurementMethod.SURFACE_INTEGRAL, 0.0)

    rows = cloud.pixel_index[:, 0]
    cols = cloud.pixel_index[:, 1]

    if ctx.config.surface_area_correction:
        normals = surface_normals(ctx.depth_map.depth, ctx.intrinsics)
        patch = np.linalg.norm(normals[rows, cols], axis=-1)
        # Extreme slant (grazing view) makes the Jacobian explode; cap the
        # per-pixel area at what a 75-degree tilt would give, beyond which the
        # depth gradient is noise rather than geometry.
        z = ctx.depth_map.depth[rows, cols].astype(np.float64)
        frontal = z * z / (ctx.intrinsics.fx * ctx.intrinsics.fy)
        patch = np.minimum(patch, frontal / math.cos(math.radians(75.0)))
        method = MeasurementMethod.SURFACE_INTEGRAL
    else:
        z = ctx.depth_map.depth[rows, cols].astype(np.float64)
        patch = z * z / (ctx.intrinsics.fx * ctx.intrinsics.fy)
        method = MeasurementMethod.SURFACE_INTEGRAL

    # The cloud may have been subsampled; scale back to the full pixel set.
    sampled = len(cloud)
    total_px = max(sampled, report.after_outlier_px)
    area = float(patch.sum()) * (total_px / sampled)

    # Area ~ Z^2, so the relative depth-scale error doubles; the focal error
    # enters twice as well (once per lateral dimension).
    rel = math.sqrt((2.0 * ctx.budget.depth_scale_sigma) ** 2 + (2.0 * ctx.budget.focal_sigma) ** 2)
    # Eroded pixels are missing area; scale by the silhouette that was removed.
    if report.retention > 0.05:
        area /= max(0.35, report.retention) if report.retention < 1.0 else 1.0

    return Measured(area, area * rel, Unit.SQUARE_METRE, method, confidence=report.retention)


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------
def estimate_volume(
    cloud: PointCloud,
    ctx: MeasurementContext,
    box: OrientedBox,
    dims: Dimensions,
) -> tuple[Measured, dict[str, float]]:
    """Approximate the object's volume, plus every alternative model.

    Monocular volume is fundamentally an inference, not a measurement: one
    viewpoint never sees the back of an object. Four models are computed and
    the policy picks between them:

    ``extrusion``
        Footprint area x height. The best model for anything standing on a
        support surface, and the default when a plane is available.
    ``hull``
        Convex hull of the visible surface closed onto the support plane.
        Follows the true silhouette rather than assuming a rectangle, so it is
        better for irregular objects; overestimates concave ones.
    ``obb``
        The oriented box's volume. A strict upper bound for convex objects.
    ``ellipsoid``
        The inscribed ellipsoid, ``pi/6 ~ 0.52`` of the box. Right for
        rounded/organic objects, which a box overestimates by ~91%.

    Returns:
        ``(chosen, alternatives)`` where ``alternatives`` maps method name to
        raw volume in m^3.
    """
    cfg = ctx.config
    points = cloud.points
    alternatives: dict[str, float] = {}

    obb_volume = float(np.prod([dims.length.value, dims.width.value, dims.height.value]))
    alternatives["obb"] = obb_volume
    alternatives["ellipsoid"] = ellipsoid_volume(
        np.array([dims.length.value, dims.width.value, dims.height.value])
    )

    footprint = box.footprint_area
    if footprint > 0:
        alternatives["extrusion"] = footprint * dims.height.value

    if ctx.plane is not None:
        try:
            # Trim in the object's own frame: a convex hull is defined by its
            # extreme points, so trimming along the box axes (rather than the
            # camera axes) removes measurement noise without clipping the
            # object's real corners.
            core = trim_to_core(points, cfg.obb_percentile, box.axes)
            hull_v, hull_footprint = closed_hull_volume(core, ctx.plane, percentile=0.0)
            alternatives["hull"] = hull_v
            if hull_footprint > 0:
                alternatives["extrusion"] = hull_footprint * dims.height.value
        except DegenerateGeometryError:
            pass
    else:
        try:
            core = trim_to_core(points, cfg.obb_percentile, box.axes)
            alternatives["hull"] = mirrored_hull_volume(core)
        except DegenerateGeometryError:
            pass

    # -- policy ------------------------------------------------------------
    method_key = cfg.volume_method
    if method_key == "auto":
        if ctx.plane is not None and "extrusion" in alternatives:
            method_key = "extrusion"
        elif "hull" in alternatives:
            method_key = "hull"
        else:
            method_key = "obb"

    if method_key not in alternatives:
        method_key = "obb"

    value = alternatives[method_key]
    method = {
        "obb": MeasurementMethod.OBB_3D,
        "hull": MeasurementMethod.CONVEX_HULL,
        "extrusion": MeasurementMethod.EXTRUSION,
        "ellipsoid": MeasurementMethod.ELLIPSOID,
    }[method_key]

    # Volume is a triple product of lengths that all ride on the same metric
    # scale, so the scale error enters three times *coherently* -- see
    # product_uncertainty for why that is not a quadrature sum.
    _, sigma = product_uncertainty(
        [dims.length.value, dims.width.value, dims.height.value],
        [dims.length.sigma, dims.width.sigma, dims.height.sigma],
        shared_relative=ctx.budget.depth_scale_sigma,
    )
    if obb_volume > 0:
        sigma *= value / obb_volume  # rescale to the chosen model

    # Model disagreement is a real epistemic uncertainty and belongs in the
    # error bar: if hull and extrusion differ by 30%, the shape assumptions are
    # doing more work than the measurement is.
    spread = 0.0
    candidates = [v for k, v in alternatives.items() if k != "ellipsoid" and v > 0]
    if len(candidates) > 1 and value > 0:
        spread = (max(candidates) - min(candidates)) / 2.0
    sigma = math.hypot(sigma, spread * 0.5)

    confidence = 1.0
    if value > 0 and spread > 0:
        confidence = float(np.clip(1.0 - spread / value, 0.1, 1.0))

    return (
        Measured(value, sigma, Unit.CUBIC_METRE, method, confidence),
        {k: round(v, 8) for k, v in alternatives.items()},
    )


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------
def estimate_distances(
    cloud: PointCloud, ctx: MeasurementContext
) -> tuple[Measured, Measured, NDArray[np.float64]]:
    """Range to the object's centroid and to its nearest surface point.

    Returns:
        ``(centroid_distance, nearest_distance, centroid_xyz)``.
    """
    points = cloud.points
    centroid = points.mean(axis=0)
    dist = float(np.linalg.norm(centroid))

    ranges = np.linalg.norm(points, axis=1)
    # 1st percentile rather than the minimum -- a single near-camera outlier
    # would otherwise define the "nearest point".
    near = float(np.percentile(ranges, 1.0))

    n = len(cloud)
    # Range error is dominated by the metric scale; the random part averages
    # down over the cloud.
    rel_sys = ctx.budget.depth_scale_sigma
    rel_rand = ctx.budget.depth_noise_sigma / math.sqrt(max(1.0, math.sqrt(n)))
    rel = math.hypot(rel_sys, rel_rand)

    return (
        Measured(dist, dist * rel, Unit.METRE, MeasurementMethod.CENTROID),
        Measured(near, near * rel, Unit.METRE, MeasurementMethod.NEAREST_POINT),
        centroid,
    )


def pairwise_distance(a: PointCloud, b: PointCloud, budget: ErrorBudget) -> Measured:
    """Centre-to-centre distance between two objects.

    The shared metric-scale error is common to both objects, so it does *not*
    partially cancel -- it scales the separation by the same factor. It
    therefore enters once, linearly.
    """
    ca, cb = a.centroid, b.centroid
    d = float(np.linalg.norm(ca - cb))
    rel = math.hypot(budget.depth_scale_sigma, budget.depth_noise_sigma * 0.5)
    return Measured(d, d * rel, Unit.METRE, MeasurementMethod.CENTROID)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
def compute_confidence(
    *,
    detection_score: float,
    mask_iou: float,
    mask_stability: float,
    report: FilterReport,
    box: OrientedBox,
    n_points: int,
    min_points: int,
    truncated: bool,
    focal_uncertainty: float,
    depth_coverage: float,
) -> tuple[float, list[str]]:
    """Composite quality score in [0, 1], with human-readable warnings.

    A weighted geometric mean is used rather than an average: any single factor
    approaching zero should drag the whole score down, because these are
    conjunctive requirements. A perfect mask on a truncated object is still not
    a usable measurement.

    This is deliberately distinct from the statistical ``sigma`` on each
    quantity. Sigma says "how wide is the error bar assuming the method
    applies"; confidence says "does the method apply at all".
    """
    warnings: list[str] = []

    factors: list[tuple[float, float]] = []  # (score, weight)

    factors.append((float(np.clip(detection_score, 0.01, 1.0)), 1.0))
    factors.append((float(np.clip(0.5 * (mask_iou + mask_stability), 0.01, 1.0)), 1.5))

    retention = float(np.clip(report.retention, 0.01, 1.0))
    factors.append((retention, 1.0))
    if retention < 0.3:
        warnings.append(f"only {retention:.0%} of mask pixels survived filtering")

    sufficiency = float(
        np.clip(math.log10(max(n_points, 1) / min_points + 1) / math.log10(11), 0.05, 1.0)
    )
    factors.append((sufficiency, 1.0))
    if n_points < min_points * 2:
        warnings.append(f"sparse point cloud ({n_points} points)")

    # A near-degenerate box means one dimension is noise, not signal.
    conditioning = float(np.clip(box.condition * 8.0, 0.15, 1.0))
    factors.append((conditioning, 0.8))
    if box.condition < 0.02:
        warnings.append("object is nearly planar; the thin dimension is unreliable")

    factors.append((float(np.clip(depth_coverage, 0.05, 1.0)), 0.5))

    # Calibration quality caps the achievable accuracy.
    calib = float(np.clip(1.0 - focal_uncertainty * 3.0, 0.2, 1.0))
    factors.append((calib, 1.2))
    if focal_uncertainty > 0.1:
        warnings.append("camera intrinsics are assumed, not calibrated; scale may be off by ~15%")

    total_weight = sum(w for _, w in factors)
    log_sum = sum(w * math.log(max(s, 1e-6)) for s, w in factors)
    score = math.exp(log_sum / total_weight)

    if truncated:
        # Truncation is a *categorical* problem, not a graded quality factor:
        # part of the object is outside the image, so the reported extent is a
        # lower bound no matter how good the mask, the depth or the
        # calibration are. Folding it in as one more term in the geometric mean
        # let a pristine measurement of a clipped object still score ~0.79.
        # Capping expresses the real semantics -- this number is not a
        # measurement of the object, whatever else went right.
        score = min(score, _TRUNCATED_CONFIDENCE_CAP)
        warnings.append(
            "object is clipped by the frame border; true extent exceeds what is visible"
        )

    for note in report.notes:
        warnings.append(f"filter: {note}")

    return float(np.clip(score, 0.0, 1.0)), warnings
