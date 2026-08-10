"""Oriented bounding boxes: free 3-D (PCA) and support-plane aligned.

Two fitters, because the right one depends on what the scene gives us:

* :func:`fit_pca_box` -- no support plane available. Uses the principal axes of
  the point cloud. Honest but biased: a single viewpoint sees a partial
  surface, and its principal axes tilt towards the visible faces.

* :func:`fit_ground_aligned_box` -- a support plane is available. The vertical
  axis is *known*, so only the in-plane rotation is free, and that reduces to a
  minimum-area rectangle over the footprint, which rotating calipers solves
  exactly. This is markedly more accurate and is the default whenever a plane
  is found.

Both use trimmed extents rather than raw min/max. A single surviving outlier
changes a min/max extent by its full displacement; trimming a small percentile
from each end costs a fraction of a percent on clean data and bounds the damage
on noisy data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull, QhullError

from measurecv.core.exceptions import DegenerateGeometryError
from measurecv.core.types import Plane

__all__ = [
    "OrientedBox",
    "RectFit",
    "fit_ground_aligned_box",
    "fit_pca_box",
    "min_area_rect",
    "principal_axes",
    "trimmed_extent",
]


@dataclass(frozen=True, slots=True)
class OrientedBox:
    """A box in camera coordinates."""

    center: NDArray[np.float64]  # (3,)
    axes: NDArray[np.float64]  # (3, 3), unit rows, right-handed
    extents: NDArray[np.float64]  # (3,) full side lengths, metres
    footprint_area: float = 0.0
    """Area of the base rectangle; exact for a ground-aligned fit."""
    condition: float = 1.0
    """Ratio of the smallest to largest principal spread. Values near 0 mean a
    near-planar cloud, where the thin axis is dominated by depth noise."""

    @property
    def volume(self) -> float:
        return float(np.prod(self.extents))

    def corners(self) -> NDArray[np.float64]:
        """The eight corners, camera coordinates."""
        signs = np.array(
            [[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)],
            dtype=np.float64,
        )
        half = self.extents * 0.5
        return self.center + (signs * half) @ self.axes


@dataclass(frozen=True, slots=True)
class RectFit:
    """Minimum-area rectangle in a 2-D frame."""

    center: NDArray[np.float64]  # (2,)
    axes: NDArray[np.float64]  # (2, 2) unit rows
    extents: NDArray[np.float64]  # (2,) side lengths
    area: float
    hull_area: float
    """Area of the actual convex footprint. ``hull_area / area`` is the
    rectangularity -- close to 1 for boxes, ~pi/4 for cylinders."""


def trimmed_extent(values: NDArray[np.float64], percentile: float = 1.0) -> tuple[float, float]:
    """Robust ``(low, high)`` bounds that are *unbiased* for a filled object.

    Taking the p-th and (100-p)-th percentiles resists outliers, but it also
    discards a real part of the object: for samples spread uniformly along an
    axis -- which is exactly what a filled silhouette gives -- the p-th
    percentile sits ``p%`` of the way in from the true edge, so a naive trimmed
    range under-measures by ``2p%``. At the default 1% trim that is a 2%
    systematic shortfall on *every* dimension, which is larger than most of the
    error sources this system works hard to control.

    The fix is to invert that relation. For a uniform distribution over
    ``[a, b]`` the trimmed range is ``(b - a)(1 - 2p/100)``, so dividing by
    that factor recovers the full extent. The bounds are then expanded
    symmetrically about the trimmed midpoint, keeping the box centre correct.

    Outlier resistance is unaffected: the percentiles still ignore the tails,
    and the correction is a fixed 1.02x at the default setting rather than
    anything that tracks the outlier's position.
    """
    if values.size == 0:
        return (0.0, 0.0)
    if percentile <= 0.0:
        return (float(values.min()), float(values.max()))

    lo, hi = np.percentile(values, [percentile, 100.0 - percentile])
    # With very few samples the percentiles can invert or collapse; fall back.
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return (float(values.min()), float(values.max()))

    coverage = 1.0 - 2.0 * percentile / 100.0
    if coverage <= 0.0:  # pragma: no cover - guarded by config validation
        return (float(lo), float(hi))

    midpoint = (lo + hi) * 0.5
    half_width = (hi - lo) * 0.5 / coverage
    # Never extrapolate beyond the data actually observed.
    return (
        max(float(values.min()), midpoint - half_width),
        min(float(values.max()), midpoint + half_width),
    )


def principal_axes(points: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Eigen-decomposition of the covariance, largest variance first.

    Returns:
        ``(axes, sqrt_eigenvalues)`` where ``axes`` rows are unit vectors and
        the second value gives the standard deviation along each axis.
    """
    if points.shape[0] < 3:
        raise DegenerateGeometryError(f"need >= 3 points for PCA, got {points.shape[0]}")

    centred = points - points.mean(axis=0)
    cov = np.cov(centred, rowvar=False)
    if not np.all(np.isfinite(cov)):
        raise DegenerateGeometryError("non-finite covariance")

    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.clip(eigenvalues[order], 0.0, None)
    axes = eigenvectors[:, order].T

    # eigh gives an orthonormal but possibly left-handed basis; enforce a
    # right-handed frame so exported poses are valid rotations.
    if np.linalg.det(axes) < 0:
        axes[2] = -axes[2]

    return axes, np.sqrt(eigenvalues)


def min_area_rect(points_2d: NDArray[np.float64]) -> RectFit:
    """Minimum-area enclosing rectangle via rotating calipers.

    The optimal rectangle always has one side collinear with an edge of the
    convex hull (Toussaint), so testing every hull edge is exact rather than
    approximate -- no angular search or local optimum to worry about.
    """
    if points_2d.shape[0] < 3:
        raise DegenerateGeometryError("need >= 3 points for a rectangle fit")

    try:
        hull = ConvexHull(points_2d)
        vertices = points_2d[hull.vertices]
        hull_area = float(hull.volume)  # 'volume' is area in 2-D
    except (QhullError, ValueError) as exc:
        raise DegenerateGeometryError(f"convex hull failed: {exc}") from exc

    if vertices.shape[0] < 3:
        raise DegenerateGeometryError("degenerate hull")

    best_area = math.inf
    best: tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]] | None = None

    n = vertices.shape[0]
    for i in range(n):
        edge = vertices[(i + 1) % n] - vertices[i]
        norm = np.linalg.norm(edge)
        if norm < 1e-12:
            continue
        u = edge / norm
        v = np.array([-u[1], u[0]])

        proj_u = vertices @ u
        proj_v = vertices @ v
        du = float(proj_u.max() - proj_u.min())
        dv = float(proj_v.max() - proj_v.min())
        area = du * dv
        if area < best_area:
            best_area = area
            centre_uv = np.array(
                [
                    (proj_u.max() + proj_u.min()) * 0.5,
                    (proj_v.max() + proj_v.min()) * 0.5,
                ]
            )
            axes = np.stack([u, v], axis=0)
            best = (centre_uv, axes, np.array([du, dv]))

    if best is None:  # pragma: no cover - implies an all-degenerate hull
        raise DegenerateGeometryError("no valid hull edge")

    centre_uv, axes, extents = best
    centre_xy = centre_uv @ axes  # back to the original 2-D frame

    # Report the longer side first for a stable length/width convention.
    if extents[1] > extents[0]:
        extents = extents[::-1].copy()
        axes = np.stack([axes[1], -axes[0]], axis=0)

    return RectFit(
        center=centre_xy,
        axes=axes,
        extents=extents,
        area=float(best_area),
        hull_area=hull_area,
    )


def fit_pca_box(points: NDArray[np.float64], percentile: float = 1.0) -> OrientedBox:
    """Free 3-D oriented box from the cloud's principal axes."""
    axes, sigmas = principal_axes(points)
    projected = (points - points.mean(axis=0)) @ axes.T

    lows = np.empty(3)
    highs = np.empty(3)
    for i in range(3):
        lows[i], highs[i] = trimmed_extent(projected[:, i], percentile)

    extents = highs - lows
    centre_local = (highs + lows) * 0.5
    center = points.mean(axis=0) + centre_local @ axes

    condition = float(sigmas[2] / sigmas[0]) if sigmas[0] > 1e-12 else 0.0
    return OrientedBox(
        center=center,
        axes=axes,
        extents=extents,
        footprint_area=float(extents[0] * extents[1]),
        condition=condition,
    )


def fit_ground_aligned_box(
    points: NDArray[np.float64],
    plane: Plane,
    percentile: float = 1.0,
    *,
    reference_axis: NDArray[np.float64] | None = None,
) -> OrientedBox:
    """Box with its vertical axis locked to the support-plane normal.

    Height is measured as the trimmed extent of the signed distance above the
    plane. Objects resting on the plane have a minimum near zero, so this is
    effectively "top of object above the floor" -- the quantity a human would
    measure with a tape.
    """
    up = plane.normal / np.linalg.norm(plane.normal)

    forward = (
        np.array([0.0, 0.0, 1.0]) if reference_axis is None else np.asarray(reference_axis, float)
    )
    projected = forward - up * float(forward @ up)
    if np.linalg.norm(projected) < 1e-6:
        alt = np.array([1.0, 0.0, 0.0])
        projected = alt - up * float(alt @ up)
    e1 = projected / np.linalg.norm(projected)
    e2 = np.cross(up, e1)
    e2 /= np.linalg.norm(e2)

    heights = points @ up + plane.d
    h_lo, h_hi = trimmed_extent(heights, percentile)
    height = h_hi - h_lo

    footprint = np.stack([points @ e1, points @ e2], axis=1)
    try:
        rect = min_area_rect(footprint)
    except DegenerateGeometryError:
        # Collinear footprint (a thin vertical object seen edge-on): fall back
        # to axis-aligned extents in the plane frame rather than failing.
        lo1, hi1 = trimmed_extent(footprint[:, 0], percentile)
        lo2, hi2 = trimmed_extent(footprint[:, 1], percentile)
        rect = RectFit(
            center=np.array([(lo1 + hi1) * 0.5, (lo2 + hi2) * 0.5]),
            axes=np.eye(2),
            extents=np.array([hi1 - lo1, hi2 - lo2]),
            area=float((hi1 - lo1) * (hi2 - lo2)),
            hull_area=float((hi1 - lo1) * (hi2 - lo2)),
        )

    # The minimum-area rectangle is fitted to the convex hull, which by
    # construction touches the most extreme point on every side -- so its
    # extents are inflated by exactly the worst outlier. The *orientation* it
    # finds is robust (it is a global property of the hull), so keep that and
    # re-derive the side lengths as trimmed extents along the rectangle's own
    # axes. Orientation from the hull, magnitude from the bulk.
    proj_a = footprint @ rect.axes[0]
    proj_b = footprint @ rect.axes[1]
    a_lo, a_hi = trimmed_extent(proj_a, percentile)
    b_lo, b_hi = trimmed_extent(proj_b, percentile)
    side_a, side_b = a_hi - a_lo, b_hi - b_lo
    rect_axes = rect.axes
    if side_b > side_a:  # preserve the "longer side first" convention
        side_a, side_b = side_b, side_a
        a_lo, a_hi, b_lo, b_hi = b_lo, b_hi, a_lo, a_hi
        rect_axes = np.stack([rect.axes[1], -rect.axes[0]], axis=0)
    rect_centre = np.array([(a_lo + a_hi) * 0.5, (b_lo + b_hi) * 0.5])

    # Lift the 2-D rectangle basis back into camera coordinates.
    plane_basis = np.stack([e1, e2], axis=0)  # (2, 3)
    axis_a = rect_axes[0] @ plane_basis
    axis_b = rect_axes[1] @ plane_basis
    axis_a /= np.linalg.norm(axis_a)
    axis_b /= np.linalg.norm(axis_b)

    axes = np.stack([axis_a, axis_b, up], axis=0)
    if np.linalg.det(axes) < 0:
        axes[1] = -axes[1]

    centre_in_plane = rect_centre @ plane_basis
    # ``centre_in_plane`` lies on the plane's own offset already because e1/e2
    # are anchored at the camera origin; add the mid-height along the normal.
    center = centre_in_plane + up * ((h_lo + h_hi) * 0.5 - float(plane.d))

    extents = np.array([side_a, side_b, height])
    condition = float(min(extents) / max(extents)) if max(extents) > 1e-12 else 0.0

    return OrientedBox(
        center=center,
        axes=axes,
        extents=extents,
        footprint_area=rect.hull_area,
        condition=condition,
    )
