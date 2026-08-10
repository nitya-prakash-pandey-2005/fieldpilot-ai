"""Exception hierarchy.

A single root (:class:`MeasureCVError`) lets the API layer map *any* internal
failure to a structured response without catching bare ``Exception`` and
accidentally swallowing programming errors from third-party code.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CalibrationError",
    "ConfigurationError",
    "DegenerateGeometryError",
    "DepthEstimationError",
    "InsufficientDataError",
    "MeasureCVError",
    "ModelLoadError",
    "SourceError",
    "UnsupportedInputError",
]


class MeasureCVError(Exception):
    """Base class for all library errors."""

    #: HTTP status the API layer should use for this failure class.
    status_code: int = 500
    #: Stable machine-readable code for clients.
    code: str = "internal_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


class ConfigurationError(MeasureCVError):
    """Invalid or contradictory configuration."""

    status_code = 500
    code = "configuration_error"


class ModelLoadError(MeasureCVError):
    """A neural backend could not be constructed (missing deps or weights)."""

    status_code = 503
    code = "model_load_error"


class CalibrationError(MeasureCVError):
    """Calibration is missing, unusable, or failed to converge."""

    status_code = 422
    code = "calibration_error"


class DepthEstimationError(MeasureCVError):
    """Depth inference produced no usable metric surface."""

    status_code = 500
    code = "depth_error"


class InsufficientDataError(MeasureCVError):
    """Too few valid 3-D samples to measure an object.

    Raised (and normally caught per-object) when a mask survives filtering with
    fewer points than the configured minimum. Reporting a dimension from a
    dozen noisy points would be worse than reporting nothing.
    """

    status_code = 422
    code = "insufficient_data"


class DegenerateGeometryError(MeasureCVError):
    """A fit is ill-conditioned -- collinear points, rank-deficient covariance."""

    status_code = 422
    code = "degenerate_geometry"


class UnsupportedInputError(MeasureCVError):
    """Unreadable or unsupported media."""

    status_code = 415
    code = "unsupported_input"


class SourceError(MeasureCVError):
    """A frame source (file, camera, RTSP URL) failed."""

    status_code = 400
    code = "source_error"
