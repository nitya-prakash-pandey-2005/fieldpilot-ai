"""Core value types shared by every subsystem.

Design notes
------------
* Plain ``dataclasses`` (not Pydantic) are used on the hot path: the pipeline
  allocates these per-object per-frame and Pydantic validation would dominate
  the frame budget. Pydantic models live at the API boundary only
  (:mod:`measurecv.api.schemas`) where validation actually buys safety.
* Every physical quantity is carried as a :class:`Measured` value -- a number
  bundled with its standard uncertainty. This makes error propagation a
  first-class concern instead of an afterthought bolted onto the output.
* All lengths are metres, all angles radians, all image coordinates pixels with
  the origin at the *centre of the top-left pixel* (OpenCV convention).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "BoundingBox",
    "DepthMap",
    "Detection",
    "Dimensions",
    "Frame",
    "InstanceMask",
    "Measured",
    "MeasurementMethod",
    "ObjectMeasurement",
    "Plane",
    "PointCloud",
    "SceneMeasurement",
    "Unit",
]


# ---------------------------------------------------------------------------
# Units and uncertain scalars
# ---------------------------------------------------------------------------
class Unit(StrEnum):
    """Physical units used by the measurement engine (SI base internally)."""

    METRE = "m"
    SQUARE_METRE = "m^2"
    CUBIC_METRE = "m^3"
    RADIAN = "rad"
    DIMENSIONLESS = ""


class MeasurementMethod(StrEnum):
    """How a given quantity was derived -- surfaced so callers can filter."""

    OBB_3D = "oriented_bbox_3d"
    """Principal-axis oriented box fitted to the metric point cloud."""

    GROUND_ALIGNED = "ground_aligned"
    """Footprint measured in an estimated support-plane frame; most accurate
    for objects resting on a floor/table."""

    PLANAR_FIT = "planar_fit"
    """Object treated as a plane patch (posters, screens, sheet goods)."""

    SURFACE_INTEGRAL = "surface_integral"
    """Per-pixel solid-angle integration of the visible surface."""

    CONVEX_HULL = "convex_hull"
    EXTRUSION = "extrusion"
    """Footprint area multiplied by height -- a prismatic volume model."""

    ELLIPSOID = "ellipsoid"
    REFERENCE_SCALE = "reference_scale"
    CENTROID = "centroid"
    NEAREST_POINT = "nearest_point"


@dataclass(frozen=True, slots=True)
class Measured:
    """A scalar with a 1-sigma standard uncertainty.

    Arithmetic on this type performs first-order (linear) error propagation
    assuming *independent* inputs. That assumption is documented rather than
    hidden: for correlated quantities use
    :func:`measurecv.geometry.uncertainty.propagate` with an explicit
    covariance matrix.
    """

    value: float
    sigma: float = 0.0
    unit: Unit = Unit.METRE
    method: MeasurementMethod | None = None
    confidence: float = 1.0
    """Heuristic quality score in [0, 1]; distinct from ``sigma``, which is a
    physical error bar. Low confidence means "few/poor samples", large sigma
    means "wide error bar"."""

    def __post_init__(self) -> None:
        if self.sigma < 0:
            raise ValueError("sigma must be non-negative")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must lie in [0, 1]")

    @property
    def relative_error(self) -> float:
        """Fractional 1-sigma error; ``inf`` for a zero-valued quantity."""
        return self.sigma / abs(self.value) if self.value else math.inf

    def interval(self, k: float = 2.0) -> tuple[float, float]:
        """Coverage interval at ``k`` sigma (k=2 ~ 95% for a normal error)."""
        return (self.value - k * self.sigma, self.value + k * self.sigma)

    def to(self, scale: float, unit: Unit) -> Measured:
        """Rescale into another unit (e.g. metres -> millimetres)."""
        return Measured(
            self.value * scale,
            self.sigma * scale,
            unit,
            self.method,
            self.confidence,
        )

    # -- linear error propagation ------------------------------------------
    def __add__(self, other: Measured | float) -> Measured:
        if isinstance(other, int | float):
            return Measured(self.value + other, self.sigma, self.unit, self.method, self.confidence)
        return Measured(
            self.value + other.value,
            math.hypot(self.sigma, other.sigma),
            self.unit,
            None,
            min(self.confidence, other.confidence),
        )

    def __sub__(self, other: Measured | float) -> Measured:
        if isinstance(other, int | float):
            return Measured(self.value - other, self.sigma, self.unit, self.method, self.confidence)
        return Measured(
            self.value - other.value,
            math.hypot(self.sigma, other.sigma),
            self.unit,
            None,
            min(self.confidence, other.confidence),
        )

    def __mul__(self, other: Measured | float) -> Measured:
        if isinstance(other, int | float):
            return Measured(
                self.value * other, self.sigma * abs(other), self.unit, self.method, self.confidence
            )
        # sigma_f/f = hypot(sigma_a/a, sigma_b/b)
        value = self.value * other.value
        rel = math.hypot(self.relative_error, other.relative_error)
        sigma = abs(value) * rel if math.isfinite(rel) else 0.0
        return Measured(
            value,
            sigma,
            _mul_unit(self.unit, other.unit),
            None,
            min(self.confidence, other.confidence),
        )

    __rmul__ = __mul__
    __radd__ = __add__

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready representation, rounded to a sane number of digits."""
        return {
            "value": round(self.value, 6),
            "sigma": round(self.sigma, 6),
            "unit": self.unit.value,
            "confidence": round(self.confidence, 4),
            "method": self.method.value if self.method else None,
            "interval_95": [round(v, 6) for v in self.interval(1.96)],
        }


_UNIT_PRODUCT: dict[tuple[Unit, Unit], Unit] = {
    (Unit.METRE, Unit.METRE): Unit.SQUARE_METRE,
    (Unit.METRE, Unit.SQUARE_METRE): Unit.CUBIC_METRE,
    (Unit.SQUARE_METRE, Unit.METRE): Unit.CUBIC_METRE,
}


def _mul_unit(a: Unit, b: Unit) -> Unit:
    if a is Unit.DIMENSIONLESS:
        return b
    if b is Unit.DIMENSIONLESS:
        return a
    return _UNIT_PRODUCT.get((a, b), Unit.DIMENSIONLESS)


# ---------------------------------------------------------------------------
# Image-space primitives
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Axis-aligned box in pixel coordinates, ``xyxy`` order, inclusive-exclusive."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(f"degenerate box: {self.as_tuple()}")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) * 0.5, (self.y1 + self.y2) * 0.5)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)

    def as_array(self) -> NDArray[np.float32]:
        return np.array(self.as_tuple(), dtype=np.float32)

    def clip(self, width: int, height: int) -> BoundingBox:
        """Clamp to image bounds; used before cropping or mask indexing."""
        return BoundingBox(
            max(0.0, min(self.x1, width - 1.0)),
            max(0.0, min(self.y1, height - 1.0)),
            max(0.0, min(self.x2, float(width))),
            max(0.0, min(self.y2, float(height))),
        )

    def expand(self, ratio: float, width: int, height: int) -> BoundingBox:
        """Grow by ``ratio`` on each side (context padding for SAM prompts)."""
        dx, dy = self.width * ratio, self.height * ratio
        return BoundingBox(self.x1 - dx, self.y1 - dy, self.x2 + dx, self.y2 + dy).clip(
            width, height
        )

    def iou(self, other: BoundingBox) -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def touches_border(self, width: int, height: int, tol: float = 2.0) -> bool:
        """True when the object is clipped by the frame edge.

        Truncated objects cannot be measured reliably -- their true extent is
        outside the image -- so the engine flags them instead of reporting a
        confidently wrong number.
        """
        return self.x1 <= tol or self.y1 <= tol or self.x2 >= width - tol or self.y2 >= height - tol


@dataclass(slots=True)
class Detection:
    """One RT-DETR detection."""

    bbox: BoundingBox
    score: float
    label_id: int
    label: str
    track_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": [round(v, 2) for v in self.bbox.as_tuple()],
            "score": round(self.score, 4),
            "label": self.label,
            "label_id": self.label_id,
            "track_id": self.track_id,
        }


@dataclass(slots=True)
class InstanceMask:
    """A binary instance mask produced by SAM 2.

    Stored as a full-resolution boolean array. ``iou_score`` is SAM's own
    predicted IoU, ``stability`` the mask stability score -- both feed the
    final confidence model.
    """

    mask: NDArray[np.bool_]
    iou_score: float = 1.0
    stability: float = 1.0

    @property
    def area_px(self) -> int:
        return int(self.mask.sum())

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.mask.shape[0]), int(self.mask.shape[1]))

    def bbox(self) -> BoundingBox | None:
        """Tight box around the mask, or ``None`` when empty."""
        rows = np.flatnonzero(self.mask.any(axis=1))
        cols = np.flatnonzero(self.mask.any(axis=0))
        if rows.size == 0 or cols.size == 0:
            return None
        return BoundingBox(float(cols[0]), float(rows[0]), float(cols[-1] + 1), float(rows[-1] + 1))


@dataclass(slots=True)
class DepthMap:
    """Metric depth in metres, plus optional per-pixel model confidence.

    ``depth`` holds *Z along the optical axis* (not ray distance) which is what
    the pinhole back-projection equations expect.
    """

    depth: NDArray[np.float32]
    confidence: NDArray[np.float32] | None = None
    scale_uncertainty: float = 0.05
    """Relative 1-sigma uncertainty of the global metric scale. Metric3D's
    absolute scale rides on the focal length, so a calibration error maps
    directly into a depth error -- this term carries that through."""

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.depth.shape[0]), int(self.depth.shape[1]))

    def valid(self, near: float = 0.05, far: float = 200.0) -> NDArray[np.bool_]:
        """Mask of physically plausible, finite depth samples."""
        return np.isfinite(self.depth) & (self.depth > near) & (self.depth < far)

    def stats(self) -> dict[str, float]:
        v = self.depth[self.valid()]
        if v.size == 0:
            return {"min": 0.0, "max": 0.0, "median": 0.0, "coverage": 0.0}
        return {
            "min": float(v.min()),
            "max": float(v.max()),
            "median": float(np.median(v)),
            "coverage": float(v.size / self.depth.size),
        }


# ---------------------------------------------------------------------------
# 3-D primitives
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class PointCloud:
    """Metric 3-D points in the camera frame (X right, Y down, Z forward)."""

    points: NDArray[np.float64]  # (N, 3)
    colors: NDArray[np.uint8] | None = None  # (N, 3)
    pixel_index: NDArray[np.int64] | None = None  # (N, 2) as (row, col)

    def __post_init__(self) -> None:
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError(f"points must be (N, 3), got {self.points.shape}")

    def __len__(self) -> int:
        return int(self.points.shape[0])

    @property
    def centroid(self) -> NDArray[np.float64]:
        return self.points.mean(axis=0)

    def subsample(self, max_points: int, rng: np.random.Generator | None = None) -> PointCloud:
        """Uniform random subsample -- keeps PCA/hull costs bounded."""
        n = len(self)
        if n <= max_points:
            return self
        rng = rng or np.random.default_rng(0xC0FFEE)
        idx = rng.choice(n, size=max_points, replace=False)
        return PointCloud(
            self.points[idx],
            self.colors[idx] if self.colors is not None else None,
            self.pixel_index[idx] if self.pixel_index is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Plane:
    """Plane ``n . x + d = 0`` with a unit normal."""

    normal: NDArray[np.float64]
    d: float
    inlier_ratio: float = 0.0
    rms_error: float = 0.0

    def signed_distance(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        return points @ self.normal + self.d

    def project(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        return points - np.outer(self.signed_distance(points), self.normal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normal": [round(float(v), 5) for v in self.normal],
            "d": round(self.d, 5),
            "inlier_ratio": round(self.inlier_ratio, 4),
            "rms_error": round(self.rms_error, 5),
        }


@dataclass(slots=True)
class Dimensions:
    """Object extent along three orthogonal axes, sorted largest-first unless
    a support plane fixes the vertical, in which case ``height`` is the
    plane-normal extent and length/width span the footprint.
    """

    length: Measured
    width: Measured
    height: Measured
    axes: NDArray[np.float64] | None = None  # (3, 3) rows = unit axis vectors
    origin: NDArray[np.float64] | None = None  # box centre in camera frame

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "length": self.length.to_dict(),
            "width": self.width.to_dict(),
            "height": self.height.to_dict(),
        }
        if self.axes is not None:
            out["axes"] = [[round(float(v), 5) for v in row] for row in self.axes]
        if self.origin is not None:
            out["origin"] = [round(float(v), 5) for v in self.origin]
        return out


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ObjectMeasurement:
    """Everything the engine knows about one physical object."""

    detection: Detection
    dimensions: Dimensions | None = None
    surface_area: Measured | None = None
    footprint_area: Measured | None = None
    volume: Measured | None = None
    distance: Measured | None = None
    """Range from the camera optical centre to the object centroid."""
    nearest_distance: Measured | None = None
    position: NDArray[np.float64] | None = None
    """Centroid in the camera frame, metres."""
    world_position: NDArray[np.float64] | None = None
    """Centroid in the ground-aligned world frame, when a support plane exists."""
    mask_area_px: int = 0
    point_count: int = 0
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def track_id(self) -> int | None:
        return self.detection.track_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "detection": self.detection.to_dict(),
            "dimensions": self.dimensions.to_dict() if self.dimensions else None,
            "surface_area": self.surface_area.to_dict() if self.surface_area else None,
            "footprint_area": self.footprint_area.to_dict() if self.footprint_area else None,
            "volume": self.volume.to_dict() if self.volume else None,
            "distance": self.distance.to_dict() if self.distance else None,
            "nearest_distance": self.nearest_distance.to_dict() if self.nearest_distance else None,
            "position": [round(float(v), 5) for v in self.position]
            if self.position is not None
            else None,
            "world_position": [round(float(v), 5) for v in self.world_position]
            if self.world_position is not None
            else None,
            "mask_area_px": self.mask_area_px,
            "point_count": self.point_count,
            "confidence": round(self.confidence, 4),
            "warnings": list(self.warnings),
            **({"extras": self.extras} if self.extras else {}),
        }


@dataclass(slots=True)
class SceneMeasurement:
    """Per-frame result: every object plus scene-level context."""

    objects: list[ObjectMeasurement]
    frame_index: int = 0
    timestamp: float = 0.0
    image_size: tuple[int, int] = (0, 0)  # (width, height)
    ground_plane: Plane | None = None
    depth_stats: dict[str, float] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    calibration_source: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.objects)

    def by_track(self, track_id: int) -> ObjectMeasurement | None:
        return next((o for o in self.objects if o.track_id == track_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "timestamp": round(self.timestamp, 4),
            "image_size": {"width": self.image_size[0], "height": self.image_size[1]},
            "objects": [o.to_dict() for o in self.objects],
            "ground_plane": self.ground_plane.to_dict() if self.ground_plane else None,
            "depth_stats": {k: round(v, 4) for k, v in self.depth_stats.items()},
            "timings_ms": {k: round(v, 2) for k, v in self.timings_ms.items()},
            "calibration_source": self.calibration_source,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class Frame:
    """A single RGB frame flowing through the pipeline."""

    image: NDArray[np.uint8]  # (H, W, 3) RGB
    index: int = 0
    timestamp: float = 0.0
    source_id: str = "default"

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)``."""
        return (int(self.image.shape[1]), int(self.image.shape[0]))
