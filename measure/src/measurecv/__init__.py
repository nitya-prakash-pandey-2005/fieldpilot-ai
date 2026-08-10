"""measurecv -- production-grade metric object measurement from RGB.

Pipeline: RT-DETR detection -> SAM 2 segmentation -> Metric3D metric depth ->
camera-calibrated geometric reconstruction -> measurement and error analysis.

Typical use::

    from measurecv import MeasurementPipeline, load_config

    pipeline = MeasurementPipeline(load_config("configs/default.yaml"))
    scene = pipeline.measure_image("desk.jpg")
    for obj in scene.objects:
        d = obj.dimensions
        print(obj.detection.label, d.length.value, "+/-", d.length.sigma, "m")

The heavy neural imports are deferred: importing this package does not import
torch, so the geometry and calibration APIs stay usable (and testable) in
environments without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from measurecv.core.config import AppConfig, load_config
from measurecv.core.logging import configure_logging, get_logger
from measurecv.core.types import (
    BoundingBox,
    DepthMap,
    Detection,
    Dimensions,
    Frame,
    InstanceMask,
    Measured,
    ObjectMeasurement,
    Plane,
    PointCloud,
    SceneMeasurement,
    Unit,
)

__version__ = "1.0.0"

if TYPE_CHECKING:  # pragma: no cover
    from measurecv.pipeline.pipeline import MeasurementPipeline

__all__ = [
    "AppConfig",
    "BoundingBox",
    "DepthMap",
    "Detection",
    "Dimensions",
    "Frame",
    "InstanceMask",
    "Measured",
    "MeasurementPipeline",
    "ObjectMeasurement",
    "Plane",
    "PointCloud",
    "SceneMeasurement",
    "Unit",
    "__version__",
    "configure_logging",
    "get_logger",
    "load_config",
]


def __getattr__(name: str) -> Any:
    """Lazily expose the pipeline so ``import measurecv`` stays lightweight."""
    if name == "MeasurementPipeline":
        from measurecv.pipeline.pipeline import MeasurementPipeline

        return MeasurementPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
