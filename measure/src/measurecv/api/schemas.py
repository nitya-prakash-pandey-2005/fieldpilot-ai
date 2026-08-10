"""API request/response models.

Pydantic is used *here and not on the hot path*. At the boundary, validation
buys real safety (rejecting a malformed camera matrix before it silently
corrupts a measurement) and generates the OpenAPI schema. Inside the pipeline
the same validation would cost more than the geometry it guards, which is why
the internal types are plain dataclasses.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "CalibrationRequest",
    "CalibrationResponse",
    "ErrorResponse",
    "HealthResponse",
    "IntrinsicsModel",
    "MeasureOptions",
    "MeasuredValue",
    "ModelsResponse",
    "ObjectModel",
    "ScaleRequest",
    "SceneResponse",
]


class MeasuredValue(BaseModel):
    """A physical quantity with its uncertainty."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "value": 0.4231,
                "sigma": 0.0219,
                "unit": "m",
                "confidence": 0.87,
                "method": "ground_aligned",
                "interval_95": [0.3802, 0.466],
            }
        }
    )

    value: float = Field(description="Point estimate, SI units")
    sigma: float = Field(description="Standard (1-sigma) uncertainty")
    unit: str
    confidence: float = Field(
        ge=0.0, le=1.0, description="Method-applicability score, not an error bar"
    )
    method: str | None = Field(default=None, description="Estimator that produced this value")
    interval_95: list[float] = Field(default_factory=list, description="95% coverage interval")


class IntrinsicsModel(BaseModel):
    """Pinhole camera model."""

    fx: float = Field(gt=0, description="Focal length in pixels, x")
    fy: float = Field(gt=0, description="Focal length in pixels, y")
    cx: float = Field(description="Principal point x, pixels")
    cy: float = Field(description="Principal point y, pixels")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    distortion: list[float] = Field(
        default_factory=list, description="Brown-Conrady k1,k2,p1,p2,k3"
    )
    source: str = "provided"
    focal_uncertainty: float = Field(default=0.02, ge=0.0, lt=1.0)
    rms_reprojection_error: float = 0.0
    hfov_deg: float | None = None
    vfov_deg: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_distortion(self) -> IntrinsicsModel:
        if self.distortion and len(self.distortion) not in (0, 4, 5, 8):
            raise ValueError(
                f"distortion must have 4, 5 or 8 coefficients, got {len(self.distortion)}"
            )
        return self


class DimensionsModel(BaseModel):
    length: MeasuredValue
    width: MeasuredValue
    height: MeasuredValue
    axes: list[list[float]] | None = Field(
        default=None, description="Box axes in camera coordinates"
    )
    origin: list[float] | None = Field(default=None, description="Box centre in camera coordinates")


class DetectionModel(BaseModel):
    bbox: list[float] = Field(description="x1, y1, x2, y2 in pixels")
    score: float
    label: str
    label_id: int
    track_id: int | None = None


class ObjectModel(BaseModel):
    """One measured object."""

    detection: DetectionModel
    dimensions: DimensionsModel | None = None
    surface_area: MeasuredValue | None = None
    footprint_area: MeasuredValue | None = None
    volume: MeasuredValue | None = None
    distance: MeasuredValue | None = None
    nearest_distance: MeasuredValue | None = None
    position: list[float] | None = Field(default=None, description="Centroid, camera frame, metres")
    world_position: list[float] | None = Field(
        default=None,
        description="Centroid in the ground-aligned frame, when a support plane exists",
    )
    mask_area_px: int = 0
    point_count: int = 0
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class PlaneModel(BaseModel):
    normal: list[float]
    d: float
    inlier_ratio: float
    rms_error: float


class SceneResponse(BaseModel):
    """A full measurement result."""

    frame_index: int = 0
    timestamp: float = 0.0
    image_size: dict[str, int]
    objects: list[ObjectModel]
    ground_plane: PlaneModel | None = None
    depth_stats: dict[str, float] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    calibration_source: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    request_id: str | None = None

    # Optional payloads, present only when requested via MeasureOptions.
    # These must be declared here: FastAPI filters responses through the
    # response_model, so an undeclared field is silently dropped rather than
    # returned -- the endpoint would appear to ignore the option entirely.
    masks: list[dict[str, Any]] | None = Field(
        default=None, description="COCO-style RLE masks, aligned with `objects`"
    )
    annotated_image_png_b64: str | None = Field(
        default=None, description="Base64 PNG of the annotated frame"
    )
    depth_png_b64: str | None = Field(
        default=None, description="Base64 PNG of the colourised depth map"
    )
    depth_range_m: dict[str, float] | None = None
    analytics: dict[str, Any] | None = Field(
        default=None, description="Scene-level counts and aggregates"
    )


class MeasureOptions(BaseModel):
    """Per-request overrides.

    Supplied as a JSON string in the ``options`` form field alongside the
    uploaded file, because multipart uploads cannot carry a JSON body.
    """

    intrinsics: IntrinsicsModel | None = Field(
        default=None, description="Explicit camera model; overrides profiles and EXIF"
    )
    use_exif: bool = Field(
        default=True, description="Read intrinsics from image EXIF when available"
    )
    classes: list[str] | None = Field(default=None, description="Restrict to these class labels")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    include_masks: bool = Field(default=False, description="Return RLE masks with the response")
    include_annotated_image: bool = Field(
        default=False, description="Return a base64 PNG of the annotated frame"
    )
    include_depth: bool = Field(default=False, description="Return a base64 PNG of the depth map")
    volume_method: Literal["auto", "obb", "hull", "extrusion", "ellipsoid"] | None = None
    dimension_method: Literal["auto", "obb", "ground_aligned", "planar"] | None = None


class ScaleRequest(BaseModel):
    """Reference-object scale refinement."""

    measured_m: list[float] = Field(min_length=1, description="Lengths this system reported")
    truth_m: list[float] = Field(min_length=1, description="True lengths of the same features")
    reference: str = "custom"

    @model_validator(mode="after")
    def _same_length(self) -> ScaleRequest:
        if len(self.measured_m) != len(self.truth_m):
            raise ValueError("measured_m and truth_m must have the same number of entries")
        return self


class CalibrationRequest(BaseModel):
    """Target-based calibration parameters."""

    board_type: Literal["chessboard", "charuco"] = "chessboard"
    board_cols: int = Field(default=9, ge=3, description="Inner corners across")
    board_rows: int = Field(default=6, ge=3, description="Inner corners down")
    square_size_m: float = Field(
        default=0.025,
        gt=0,
        description="Measure the printed target; do not trust the nominal value",
    )
    marker_size_m: float = Field(default=0.018, gt=0)
    min_views: int = Field(default=8, ge=3)
    max_rms_error_px: float = Field(default=1.0, gt=0)


class CalibrationResponse(BaseModel):
    intrinsics: IntrinsicsModel
    rms_error: float
    per_view_errors: list[float]
    accepted_views: list[str]
    rejected_views: list[dict[str, str]]
    coverage: float
    activated: bool = Field(description="Whether this profile is now in use by the pipeline")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "starting"]
    version: str
    uptime_s: float
    device: dict[str, Any]
    models_loaded: bool
    frames_processed: int
    latency_ms: dict[str, float] = Field(default_factory=dict)


class ModelsResponse(BaseModel):
    device: dict[str, Any]
    detector: dict[str, Any]
    segmenter: dict[str, Any]
    depth: dict[str, Any]
    backends: dict[str, str]


class ErrorResponse(BaseModel):
    """Structured error, matching the exception hierarchy."""

    code: str = Field(description="Stable machine-readable error code")
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
