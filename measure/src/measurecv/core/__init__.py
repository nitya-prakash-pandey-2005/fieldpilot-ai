"""Core primitives: types, configuration, logging, device and timing."""

from measurecv.core.config import AppConfig, load_config
from measurecv.core.device import DeviceContext, resolve_device
from measurecv.core.exceptions import (
    CalibrationError,
    ConfigurationError,
    DegenerateGeometryError,
    DepthEstimationError,
    InsufficientDataError,
    MeasureCVError,
    ModelLoadError,
    SourceError,
    UnsupportedInputError,
)
from measurecv.core.logging import configure_logging, get_logger
from measurecv.core.timing import StageTimer
from measurecv.core.types import (
    BoundingBox,
    DepthMap,
    Detection,
    Dimensions,
    Frame,
    InstanceMask,
    Measured,
    MeasurementMethod,
    ObjectMeasurement,
    Plane,
    PointCloud,
    SceneMeasurement,
    Unit,
)

__all__ = [
    "AppConfig",
    "BoundingBox",
    "CalibrationError",
    "ConfigurationError",
    "DegenerateGeometryError",
    "DepthEstimationError",
    "DepthMap",
    "Detection",
    "DeviceContext",
    "Dimensions",
    "Frame",
    "InstanceMask",
    "InsufficientDataError",
    "MeasureCVError",
    "Measured",
    "MeasurementMethod",
    "ModelLoadError",
    "ObjectMeasurement",
    "Plane",
    "PointCloud",
    "SceneMeasurement",
    "SourceError",
    "StageTimer",
    "Unit",
    "UnsupportedInputError",
    "configure_logging",
    "get_logger",
    "load_config",
    "resolve_device",
]
