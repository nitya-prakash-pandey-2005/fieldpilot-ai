"""Support-plane estimation and the ground-aligned world frame.

Why bother with a plane at all
------------------------------
A PCA-fitted oriented box on a partially observed object is systematically
wrong: from a single viewpoint you see at most three faces, and the principal
axes of that *visible surface* are not the object's axes. But almost every
object of practical interest rests on a horizontal support, and that support
supplies the missing constraint -- it fixes one axis exactly (the vertical) and
reduces the fit to a 2-D problem in the plane, where rotating calipers gives an
optimal answer.

Concretely: with a support plane, "height" becomes the maximum distance above
the plane (robust, needs only the top of the object to be visible), and the
footprint becomes a minimum-area rectangle over the shadow of the point cloud.
Both are far better conditioned than a free 3-D box fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from measurecv.core.exceptions import DegenerateGeometryError
from measurecv.core.logging import get_logger
from measurecv.core.types import Plane, PointCloud

log = get_logger(__name__)

__all__ = ["SupportFrame", "estimate_support_plane", "fit_plane_lsq", "fit_plane_ransac"]

#: Camera-frame "up" under the OpenCV convention (X right, Y down, Z forward).
CAMERA_UP = np.array([0.0, -1.0, 0.0], dtype=np.float64)


def fit_plane_lsq(points: NDArray[np.float64]) -> Plane:
    """Total least-squares plane through points (SVD of the centred matrix).

    Unlike an ordinary least-squares fit of ``z = ax + by + c``, this minimises
    the *orthogonal* distance and is therefore invariant to the plane's
    orientation -- essential when the plane may be near-vertical in the camera
    frame.
    """
    if points.shape[0] < 3:
        raise DegenerateGeometryError(f"need >= 3 points to fit a plane, got {points.shape[0]}")

    centroid = points.mean(axis=0)
    centred = points - centroid
    try:
        _, singular, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - numerical edge case
        raise DegenerateGeometryError(f"plane SVD failed: {exc}") from exc

    # Near-equal smallest singular values mean the points are not planar
    # (a blob rather than a surface) and the normal is arbitrary.
    if singular[1] <= 1e-12 or singular[2] / max(singular[1], 1e-12) > 0.9:
        raise DegenerateGeometryError(
            "points are not planar enough to define a normal",
            singular_values=singular.tolist(),
        )

    normal = vt[2]
    normal = normal / np.linalg.norm(normal)
    d = -float(normal @ centroid)
    residuals = points @ normal + d
    return Plane(
        normal=normal,
        d=d,
        inlier_ratio=1.0,
        rms_error=float(np.sqrt(np.mean(residuals**2))),
    )


def fit_plane_ransac(
    points: NDArray[np.float64],
    *,
    distance_threshold: float = 0.02,
    max_iterations: int = 600,
    min_inlier_ratio: float = 0.15,
    normal_prior: NDArray[np.float64] | None = None,
    max_prior_angle_deg: float = 35.0,
    confidence: float = 0.999,
    seed: int = 0xBEEF,
    max_scoring_points: int = 20000,
) -> Plane | None:
    """RANSAC plane fit with an optional orientation prior.

    The prior is what stops the fit latching onto a wall or a table's side
    panel, which are often larger in a point cloud than the floor itself.
    Candidate planes whose normal is further than ``max_prior_angle_deg`` from
    ``normal_prior`` are rejected before scoring, which also makes the search
    cheaper.

    Iterations adapt to the best inlier ratio found so far (the standard RANSAC
    stopping rule), so a clean scene terminates in a few dozen trials rather
    than always running the full budget.

    Returns:
        The refined plane, or ``None`` if no hypothesis reached
        ``min_inlier_ratio``.
    """
    n = points.shape[0]
    if n < 3:
        return None

    rng = np.random.default_rng(seed)

    # Score against a bounded subsample: RANSAC scoring is O(iterations * N)
    # and beyond ~20k points the inlier ratio estimate is already exact enough.
    if n > max_scoring_points:
        idx = rng.choice(n, max_scoring_points, replace=False)
        scoring = points[idx]
    else:
        scoring = points

    prior = None
    if normal_prior is not None:
        prior = normal_prior / np.linalg.norm(normal_prior)
    cos_limit = math.cos(math.radians(max_prior_angle_deg))

    best_inliers: NDArray[np.bool_] | None = None
    best_count = 0
    iterations = max_iterations
    trial = 0

    while trial < min(iterations, max_iterations):
        trial += 1
        sample = points[rng.choice(n, 3, replace=False)]
        v1 = sample[1] - sample[0]
        v2 = sample[2] - sample[0]
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-12:  # collinear sample
            continue
        normal = normal / norm

        # Sign is arbitrary from a cross product, so compare |cos|.
        if prior is not None and abs(float(normal @ prior)) < cos_limit:
            continue

        d = -float(normal @ sample[0])
        inliers = np.abs(scoring @ normal + d) <= distance_threshold
        count = int(inliers.sum())

        if count > best_count:
            best_count = count
            best_inliers = inliers
            ratio = count / scoring.shape[0]
            if ratio > 0.0:
                # Adaptive stopping: how many trials to see one all-inlier
                # sample with probability `confidence`.
                denom = math.log(max(1e-12, 1.0 - ratio**3))
                iterations = math.ceil(math.log(1.0 - confidence) / denom)

    if best_inliers is None or best_count / scoring.shape[0] < min_inlier_ratio:
        return None

    # Refit on all inliers (from the full cloud, not just the subsample) --
    # the minimal sample only ever gives a coarse hypothesis.
    inlier_points = scoring[best_inliers]
    try:
        refined = fit_plane_lsq(inlier_points)
    except DegenerateGeometryError:
        return None

    final_inliers = np.abs(points @ refined.normal + refined.d) <= distance_threshold
    ratio = float(final_inliers.mean())
    residuals = points[final_inliers] @ refined.normal + refined.d
    return Plane(
        normal=refined.normal,
        d=refined.d,
        inlier_ratio=ratio,
        rms_error=float(np.sqrt(np.mean(residuals**2))) if residuals.size else 0.0,
    )


def estimate_support_plane(
    cloud: PointCloud,
    *,
    distance_threshold: float = 0.02,
    max_iterations: int = 600,
    min_inlier_ratio: float = 0.12,
    gravity_prior_deg: float = 35.0,
    up_hint: NDArray[np.float64] | None = None,
) -> Plane | None:
    """Find the dominant horizontal support surface in a scene cloud.

    The returned plane's normal is oriented to point *towards* the camera's
    up direction, so ``signed_distance`` is positive above the surface. That
    sign convention is relied on by the height estimator.
    """
    if len(cloud) < 50:
        return None

    up = up_hint if up_hint is not None else CAMERA_UP
    plane = fit_plane_ransac(
        cloud.points,
        distance_threshold=distance_threshold,
        max_iterations=max_iterations,
        min_inlier_ratio=min_inlier_ratio,
        normal_prior=up,
        max_prior_angle_deg=gravity_prior_deg,
    )
    if plane is None:
        log.debug("support_plane_not_found", points=len(cloud))
        return None

    normal = plane.normal
    d = plane.d
    if float(normal @ up) < 0:
        normal, d = -normal, -d

    oriented = Plane(normal=normal, d=d, inlier_ratio=plane.inlier_ratio, rms_error=plane.rms_error)
    log.debug(
        "support_plane_found",
        inlier_ratio=round(oriented.inlier_ratio, 3),
        rms=round(oriented.rms_error, 4),
        tilt_deg=round(math.degrees(math.acos(min(1.0, abs(float(normal @ up))))), 2),
    )
    return oriented


@dataclass(frozen=True, slots=True)
class SupportFrame:
    """An orthonormal world frame anchored to a support plane.

    Axes: ``x`` and ``y`` span the plane, ``z`` is the plane normal (up). A
    point's world ``z`` is therefore its height above the support surface,
    which is exactly the quantity the height estimator wants.
    """

    rotation: NDArray[np.float64]  # (3, 3), rows are the world axes in camera coords
    origin: NDArray[np.float64]  # a point on the plane, camera coords
    plane: Plane

    @classmethod
    def from_plane(cls, plane: Plane, reference: NDArray[np.float64] | None = None) -> SupportFrame:
        """Build a frame from a plane.

        The in-plane axes are otherwise arbitrary; anchoring ``x`` to the
        projection of the camera's optical axis makes the frame deterministic
        and keeps reported footprint axes stable from frame to frame.
        """
        up = plane.normal / np.linalg.norm(plane.normal)

        forward = np.array([0.0, 0.0, 1.0]) if reference is None else np.asarray(reference, float)
        projected = forward - up * float(forward @ up)
        norm = np.linalg.norm(projected)
        if norm < 1e-6:
            # Optical axis parallel to the normal (camera looking straight
            # down) -- pick any orthogonal direction.
            alt = np.array([1.0, 0.0, 0.0])
            projected = alt - up * float(alt @ up)
            norm = np.linalg.norm(projected)
            if norm < 1e-6:  # pragma: no cover - unreachable for a unit normal
                raise DegenerateGeometryError("cannot construct an in-plane axis")
        x_axis = projected / norm
        y_axis = np.cross(up, x_axis)
        y_axis /= np.linalg.norm(y_axis)

        rotation = np.stack([x_axis, y_axis, up], axis=0)
        origin = -plane.d * up  # closest point on the plane to the camera centre
        return cls(rotation=rotation, origin=origin, plane=plane)

    def to_world(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """Camera-frame points -> support-plane frame."""
        return (points - self.origin) @ self.rotation.T

    def to_camera(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """Support-plane frame -> camera frame."""
        return points @ self.rotation + self.origin

    def height_above(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """Signed height above the support plane (metres)."""
        return points @ self.plane.normal + self.plane.d
