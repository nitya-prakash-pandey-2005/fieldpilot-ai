"""Shared fixtures.

The synthetic scene fixtures are the backbone of the accuracy tests: they build
images whose true metric dimensions are known *analytically*, so assertions can
be made against ground truth rather than against whatever the code happened to
produce when the test was written.
"""

from __future__ import annotations

import numpy as np
import pytest

from measurecv.calibration.intrinsics import CameraIntrinsics, intrinsics_from_fov
from measurecv.core.config import AppConfig, MeasurementConfig
from measurecv.core.types import DepthMap, InstanceMask
from measurecv.models.synthetic import SYNTHETIC_CAMERA_HEIGHT_M, ground_depth

WIDTH, HEIGHT = 640, 480
HFOV = 60.0


@pytest.fixture
def intrinsics() -> CameraIntrinsics:
    """A 640x480 camera with a 60-degree horizontal field of view."""
    return intrinsics_from_fov(WIDTH, HEIGHT, HFOV)


@pytest.fixture
def rng() -> np.random.Generator:
    """Seeded generator -- every accuracy test must be reproducible."""
    return np.random.default_rng(20240611)


@pytest.fixture
def synthetic_config() -> AppConfig:
    """Config with all neural backends replaced by deterministic doubles."""
    config = AppConfig().synthetic()
    config.calibration.default_hfov_deg = HFOV
    config.log_level = "WARNING"
    return config


@pytest.fixture
def measurement_config() -> MeasurementConfig:
    return MeasurementConfig(mask_erode_px=2, min_points=50)


@pytest.fixture
def pipeline(synthetic_config: AppConfig):
    """A pipeline wired to the synthetic backends."""
    from measurecv.pipeline.pipeline import MeasurementPipeline

    return MeasurementPipeline(synthetic_config)


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------
@pytest.fixture
def billboard_scene() -> dict:
    """An object standing on the ground plane, with analytic ground truth.

    The synthetic depth backend places each foreground blob at the depth its
    base row implies on the ground plane, so a blob spanning rows
    ``[top, base)`` has a true height of ``h * (base - top) / (base - cy)`` and
    a true width of ``(cols) * Z / fx``. Those closed forms are what the
    accuracy tests assert against.
    """
    k = intrinsics_from_fov(WIDTH, HEIGHT, HFOV)
    top, base, left, right = 300, 400, 280, 360

    image = np.full((HEIGHT, WIDTH, 3), 90, np.uint8)
    image[top:base, left:right] = (220, 60, 40)

    denominator = base - k.cy
    depth_z = k.fy * SYNTHETIC_CAMERA_HEIGHT_M / denominator

    return {
        "image": image,
        "intrinsics": k,
        "true_depth_m": depth_z,
        "true_height_m": SYNTHETIC_CAMERA_HEIGHT_M * (base - top) / denominator,
        "true_width_m": (right - left) * depth_z / k.fx,
        "bbox": (left, top, right, base),
    }


@pytest.fixture
def fronto_plate() -> dict:
    """A flat rectangle facing the camera at a known depth.

    The simplest case with an exact answer, which makes it the right place to
    verify that lateral extents and the boundary-shrink compensation are
    correct without any shape modelling in the way.
    """
    k = intrinsics_from_fov(WIDTH, HEIGHT, HFOV)
    depth_z = 2.0
    plate_w, plate_h = 0.50, 0.30

    depth = np.full((HEIGHT, WIDTH), 40.0, np.float32)
    uu, vv = np.meshgrid(np.arange(WIDTH), np.arange(HEIGHT))
    x = (uu - k.cx) * depth_z / k.fx
    y = (vv - k.cy) * depth_z / k.fy
    mask = (np.abs(x) <= plate_w / 2) & (np.abs(y) <= plate_h / 2)
    depth[mask] = depth_z

    return {
        "intrinsics": k,
        "depth_map": DepthMap(depth, scale_uncertainty=0.05),
        "mask": InstanceMask(mask),
        "true_width_m": plate_w,
        "true_height_m": plate_h,
        "true_depth_m": depth_z,
    }


@pytest.fixture
def ground_scene_cloud() -> dict:
    """A dense point cloud of a level floor, for plane-fitting tests."""
    k = intrinsics_from_fov(WIDTH, HEIGHT, HFOV)
    depth = ground_depth(k, SYNTHETIC_CAMERA_HEIGHT_M)
    depth[depth <= 0] = 25.0

    from measurecv.geometry.backproject import backproject_depth_map

    cloud = backproject_depth_map(DepthMap(depth), k, stride=3)
    return {
        "cloud": cloud,
        "true_normal": np.array([0.0, -1.0, 0.0]),
        "true_d": SYNTHETIC_CAMERA_HEIGHT_M,
    }


@pytest.fixture
def api_client(synthetic_config: AppConfig):
    """A FastAPI TestClient with synthetic backends and no auth."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from measurecv.api.app import create_app

    synthetic_config.api.api_keys = []
    app = create_app(synthetic_config)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def encoded_image(billboard_scene: dict) -> bytes:
    """The billboard scene as PNG bytes, for upload endpoints."""
    import cv2

    ok, buffer = cv2.imencode(".png", cv2.cvtColor(billboard_scene["image"], cv2.COLOR_RGB2BGR))
    assert ok
    return buffer.tobytes()
