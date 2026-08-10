"""Convex-hull volume estimation, including support-plane closure.

The naive approach -- convex hull of the visible points -- systematically
*underestimates* volume, often by more than half, because a single view sees
only the front surface and the hull collapses onto it like a shell.

:func:`closed_hull_volume` fixes this using the support plane: every visible
point is projected straight down onto the plane and added to the hull. The
resulting solid is the object's visible surface swept to the floor, which is
the correct model for anything resting on a surface and is exact for convex
objects. It is the same reasoning a person uses when estimating a box's volume
from one corner view.

Limits, stated plainly: for objects with concavities (a bowl, an L-shaped
bracket) the convex closure overestimates, and for objects that overhang their
own base it is optimistic. The engine reports which model produced a volume so
that these cases are attributable rather than mysterious.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull, QhullError

from measurecv.core.exceptions import DegenerateGeometryError
from measurecv.core.types import Plane

__all__ = ["closed_hull_volume", "convex_hull", "hull_metrics", "mirrored_hull_volume"]


def trim_to_core(
    points: NDArray[np.float64],
    percentile: float = 1.0,
    basis: NDArray[np.float64] | None = None,
) -> NDArray[np.float64]:
    """Drop points outside the trimmed per-axis range of ``basis``.

    A convex hull is defined entirely by its most extreme points, which makes
    raw hull volume the least robust statistic in the whole engine: sub-percent
    measurement noise inflates it by ~10%, because the noise pushes the surface
    outward on every face at once and volume goes as the cube. Restricting the
    hull to the trimmed core removes that inflation while leaving the shape
    information -- the reason to use a hull at all -- intact.
    """
    if percentile <= 0.0 or points.shape[0] < 8:
        return points

    axes = np.eye(3) if basis is None else np.asarray(basis, dtype=np.float64)
    projected = points @ axes.T
    lo = np.percentile(projected, percentile, axis=0)
    hi = np.percentile(projected, 100.0 - percentile, axis=0)
    keep = np.all((projected >= lo) & (projected <= hi), axis=1)

    # Never trim so hard that the hull becomes degenerate.
    return points[keep] if keep.sum() >= 8 else points


def convex_hull(points: NDArray[np.float64]) -> ConvexHull:
    """Convex hull with a useful error on degenerate input."""
    if points.shape[0] < 4:
        raise DegenerateGeometryError(f"need >= 4 points for a 3-D hull, got {points.shape[0]}")
    try:
        # QJ (joggle) perturbs coincident/coplanar inputs so nearly-flat point
        # clouds -- common for thin objects -- still produce a valid hull
        # instead of raising.
        return ConvexHull(points, qhull_options="QJ")
    except (QhullError, ValueError) as exc:
        raise DegenerateGeometryError(f"convex hull failed: {exc}") from exc


def hull_metrics(points: NDArray[np.float64]) -> tuple[float, float]:
    """``(volume, surface_area)`` of the convex hull of the visible points."""
    hull = convex_hull(points)
    return float(hull.volume), float(hull.area)


def closed_hull_volume(
    points: NDArray[np.float64], plane: Plane, percentile: float = 1.0
) -> tuple[float, float]:
    """Volume of the visible surface extruded onto its support plane.

    Args:
        points: ``(N, 3)`` camera-frame cloud.
        plane: Support plane, normal pointing away from the surface.
        percentile: Robust trim applied per axis before hulling.

    Returns:
        ``(volume, footprint_area)`` in m^3 and m^2.
    """
    normal = plane.normal / np.linalg.norm(plane.normal)

    # Work in the plane's own basis so the trim is applied along physically
    # meaningful directions (two in-plane, one vertical).
    ref = np.array([0.0, 0.0, 1.0])
    e1 = ref - normal * float(ref @ normal)
    if np.linalg.norm(e1) < 1e-6:
        ref = np.array([1.0, 0.0, 0.0])
        e1 = ref - normal * float(ref @ normal)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(normal, e1)
    basis = np.stack([e1, e2, normal], axis=0)

    core = trim_to_core(points, percentile, basis)

    heights = core @ normal + plane.d
    # Ignore points below the plane (noise, or the plane cutting the object).
    above = core[heights > 0]
    if above.shape[0] < 4:
        above = core

    projected = above - np.outer(above @ normal + plane.d, normal)
    combined = np.vstack([above, projected])

    hull = convex_hull(combined)
    volume = float(hull.volume)

    footprint_2d = np.stack([projected @ e1, projected @ e2], axis=1)
    try:
        footprint_area = float(ConvexHull(footprint_2d).volume)  # 'volume' == area in 2-D
    except (QhullError, ValueError):
        footprint_area = 0.0

    return volume, footprint_area


def mirrored_hull_volume(
    points: NDArray[np.float64], view_direction: NDArray[np.float64] | None = None
) -> float:
    """Volume assuming front/back symmetry about the object's mid-depth plane.

    The fallback when no support plane exists. The visible surface is mirrored
    through the plane at the cloud's median depth, and the hull of both halves
    is taken. This is exact for symmetric objects (bottles, balls, most
    manufactured goods viewed head-on) and biased for asymmetric ones -- which
    is still a far better model than the shell-like hull of one surface.
    """
    view = np.array([0.0, 0.0, 1.0]) if view_direction is None else view_direction
    view = view / np.linalg.norm(view)

    along = points @ view
    # Mirror about the *far* surface: the unseen back of the object lies beyond
    # the deepest visible points, not beyond the median.
    pivot = float(np.percentile(along, 95.0))
    mirrored = points + np.outer(2.0 * (pivot - along), view)

    combined = np.vstack([points, mirrored])
    hull = convex_hull(combined)
    return float(hull.volume)


def ellipsoid_volume(extents: NDArray[np.float64]) -> float:
    """Volume of the ellipsoid inscribed in a box of the given side lengths.

    Useful for organic/rounded objects (fruit, produce, livestock) where a box
    overestimates by the ratio ``6/pi ~ 1.91``.
    """
    a, b, c = (float(e) * 0.5 for e in extents)
    return float(4.0 / 3.0 * np.pi * a * b * c)
