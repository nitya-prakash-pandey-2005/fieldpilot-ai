"""Core type and configuration tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from measurecv.core.config import AppConfig, load_config
from measurecv.core.exceptions import ConfigurationError, MeasureCVError
from measurecv.core.timing import RollingStats, StageTimer
from measurecv.core.types import (
    BoundingBox,
    DepthMap,
    Detection,
    InstanceMask,
    Measured,
    MeasurementMethod,
    PointCloud,
    Unit,
)


class TestMeasured:
    def test_rejects_negative_sigma(self) -> None:
        with pytest.raises(ValueError, match="sigma"):
            Measured(1.0, -0.1)

    def test_rejects_out_of_range_confidence(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Measured(1.0, 0.1, confidence=1.5)

    def test_addition_uses_quadrature(self) -> None:
        result = Measured(1.0, 0.3) + Measured(2.0, 0.4)
        assert result.value == pytest.approx(3.0)
        assert result.sigma == pytest.approx(0.5)  # hypot(0.3, 0.4)

    def test_multiplication_combines_relative_errors(self) -> None:
        result = Measured(2.0, 0.2) * Measured(3.0, 0.3)
        assert result.value == pytest.approx(6.0)
        # rel = hypot(0.1, 0.1) = 0.1414 -> sigma = 6 * 0.1414
        assert result.sigma == pytest.approx(6.0 * math.hypot(0.1, 0.1))

    def test_multiplication_derives_units(self) -> None:
        area = Measured(2.0, 0.0, Unit.METRE) * Measured(3.0, 0.0, Unit.METRE)
        assert area.unit is Unit.SQUARE_METRE
        volume = area * Measured(4.0, 0.0, Unit.METRE)
        assert volume.unit is Unit.CUBIC_METRE

    def test_scalar_multiplication_scales_sigma(self) -> None:
        result = Measured(2.0, 0.1) * 3
        assert result.value == pytest.approx(6.0)
        assert result.sigma == pytest.approx(0.3)

    def test_relative_error_of_zero_is_infinite(self) -> None:
        assert Measured(0.0, 0.1).relative_error == math.inf

    def test_coverage_interval(self) -> None:
        low, high = Measured(1.0, 0.1).interval(k=2.0)
        assert low == pytest.approx(0.8)
        assert high == pytest.approx(1.2)

    def test_unit_conversion(self) -> None:
        millimetres = Measured(1.5, 0.02, Unit.METRE).to(1000.0, Unit.METRE)
        assert millimetres.value == pytest.approx(1500.0)
        assert millimetres.sigma == pytest.approx(20.0)

    def test_serialisation_shape(self) -> None:
        payload = Measured(1.0, 0.05, Unit.METRE, MeasurementMethod.OBB_3D, 0.9).to_dict()
        assert payload["unit"] == "m"
        assert payload["method"] == "oriented_bbox_3d"
        assert len(payload["interval_95"]) == 2

    def test_is_immutable(self) -> None:
        value = Measured(1.0, 0.1)
        with pytest.raises(AttributeError):
            value.value = 2.0  # type: ignore[misc]


class TestBoundingBox:
    def test_rejects_inverted_box(self) -> None:
        with pytest.raises(ValueError, match="degenerate"):
            BoundingBox(10, 10, 5, 20)

    def test_geometry(self) -> None:
        box = BoundingBox(10, 20, 110, 70)
        assert box.width == 100
        assert box.height == 50
        assert box.area == 5000
        assert box.centre == (60.0, 45.0)

    def test_iou(self) -> None:
        a = BoundingBox(0, 0, 10, 10)
        assert a.iou(a) == pytest.approx(1.0)
        assert a.iou(BoundingBox(20, 20, 30, 30)) == 0.0
        # Half overlap: intersection 50, union 150.
        assert a.iou(BoundingBox(5, 0, 15, 10)) == pytest.approx(50 / 150)

    def test_clip_to_frame(self) -> None:
        clipped = BoundingBox(-10, -5, 700, 500).clip(640, 480)
        assert clipped.x1 == 0 and clipped.y1 == 0
        assert clipped.x2 == 640 and clipped.y2 == 480

    def test_expand_stays_inside_frame(self) -> None:
        expanded = BoundingBox(0, 0, 100, 100).expand(0.5, 640, 480)
        assert expanded.x1 >= 0 and expanded.y1 >= 0
        assert expanded.x2 <= 640

    def test_border_detection(self) -> None:
        assert BoundingBox(0, 100, 300, 400).touches_border(640, 480)
        assert not BoundingBox(50, 100, 300, 400).touches_border(640, 480)
        assert BoundingBox(50, 100, 639, 400).touches_border(640, 480)


class TestDepthMap:
    def test_valid_excludes_out_of_range(self) -> None:
        depth = np.array([[0.0, 1.0], [np.nan, 500.0]], np.float32)
        valid = DepthMap(depth).valid(near=0.05, far=200.0)
        assert valid.tolist() == [[False, True], [False, False]]

    def test_stats_on_empty_map(self) -> None:
        stats = DepthMap(np.zeros((4, 4), np.float32)).stats()
        assert stats["coverage"] == 0.0

    def test_stats_coverage(self) -> None:
        depth = np.full((10, 10), 2.0, np.float32)
        depth[:5] = 0.0
        assert DepthMap(depth).stats()["coverage"] == pytest.approx(0.5)


class TestInstanceMask:
    def test_bbox_is_tight(self) -> None:
        mask = np.zeros((100, 100), bool)
        mask[20:50, 30:70] = True
        box = InstanceMask(mask).bbox()
        assert box is not None
        assert box.as_tuple() == (30.0, 20.0, 70.0, 50.0)

    def test_empty_mask_has_no_bbox(self) -> None:
        assert InstanceMask(np.zeros((10, 10), bool)).bbox() is None

    def test_area(self) -> None:
        mask = np.zeros((10, 10), bool)
        mask[:3, :4] = True
        assert InstanceMask(mask).area_px == 12


class TestPointCloud:
    def test_rejects_wrong_shape(self) -> None:
        with pytest.raises(ValueError, match=r"\(N, 3\)"):
            PointCloud(np.zeros((10, 2)))

    def test_subsample_is_reproducible(self) -> None:
        points = np.random.default_rng(0).normal(size=(1000, 3))
        a = PointCloud(points).subsample(100, np.random.default_rng(7))
        b = PointCloud(points).subsample(100, np.random.default_rng(7))
        np.testing.assert_array_equal(a.points, b.points)

    def test_subsample_no_op_when_small(self) -> None:
        cloud = PointCloud(np.zeros((10, 3)))
        assert cloud.subsample(100) is cloud

    def test_subsample_keeps_arrays_aligned(self) -> None:
        points = np.random.default_rng(1).normal(size=(500, 3))
        colors = np.random.default_rng(2).integers(0, 255, (500, 3), dtype=np.uint8)
        pixels = np.arange(1000).reshape(500, 2)

        cloud = PointCloud(points, colors, pixels).subsample(50)

        assert len(cloud) == 50
        assert cloud.colors is not None and cloud.colors.shape == (50, 3)
        assert cloud.pixel_index is not None and cloud.pixel_index.shape == (50, 2)

    def test_centroid(self) -> None:
        cloud = PointCloud(np.array([[0.0, 0, 0], [2.0, 4, 6]]))
        np.testing.assert_allclose(cloud.centroid, [1.0, 2.0, 3.0])


class TestConfig:
    def test_defaults_validate(self) -> None:
        config = AppConfig()
        assert config.detection.model_id.startswith("PekingU/")
        assert config.depth.canonical_focal == 1000.0

    def test_synthetic_swaps_every_backend(self) -> None:
        config = AppConfig().synthetic()
        assert config.detection.backend == "synthetic"
        assert config.segmentation.backend == "synthetic"
        assert config.depth.backend == "synthetic"

    def test_ground_aligned_requires_plane_estimation(self) -> None:
        """Cross-field validation catches contradictions that would otherwise
        surface as silently wrong measurements."""
        with pytest.raises(ConfigurationError, match="estimate_ground_plane"):
            load_config(
                None,
                measurement={"dimension_method": "ground_aligned", "estimate_ground_plane": False},
            )

    def test_extrusion_volume_requires_plane(self) -> None:
        with pytest.raises(ConfigurationError, match="support plane"):
            load_config(
                None,
                measurement={"volume_method": "extrusion", "estimate_ground_plane": False},
            )

    def test_onnx_backend_requires_path(self) -> None:
        with pytest.raises(ConfigurationError, match="onnx_path"):
            load_config(None, detection={"backend": "onnx"})

    def test_depth_range_must_be_ordered(self) -> None:
        with pytest.raises(ConfigurationError, match="min_depth_m"):
            load_config(None, depth={"min_depth_m": 10.0, "max_depth_m": 1.0})

    def test_multiple_cuda_workers_rejected(self) -> None:
        """Each worker would load its own copy of the weights."""
        with pytest.raises(ConfigurationError, match="workers"):
            load_config(None, api={"workers": 4}, runtime={"device": "cuda"})

    def test_max_points_must_exceed_min(self) -> None:
        with pytest.raises(ConfigurationError, match="max_points"):
            load_config(None, measurement={"min_points": 5000, "max_points": 100})

    def test_unknown_key_is_rejected(self) -> None:
        """extra='forbid' turns a typo into an error instead of a silent no-op."""
        with pytest.raises(ConfigurationError):
            load_config(None, detection={"scoore_threshold": 0.5})

    def test_yaml_round_trip(self, tmp_path) -> None:
        import yaml

        path = tmp_path / "config.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "log_level": "DEBUG",
                    "detection": {"score_threshold": 0.7},
                    "measurement": {"mask_erode_px": 5},
                }
            )
        )
        config = load_config(path)

        assert config.log_level == "DEBUG"
        assert config.detection.score_threshold == 0.7
        assert config.measurement.mask_erode_px == 5

    def test_overrides_beat_yaml(self, tmp_path) -> None:
        import yaml

        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({"detection": {"score_threshold": 0.7}}))
        config = load_config(path, detection={"score_threshold": 0.2})
        assert config.detection.score_threshold == 0.2

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            load_config(tmp_path / "absent.yaml")

    def test_invalid_yaml_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("detection: [unclosed")
        with pytest.raises(ConfigurationError, match="invalid YAML"):
            load_config(path)

    def test_env_var_override(self, monkeypatch) -> None:
        monkeypatch.setenv("MEASURECV__DETECTION__SCORE_THRESHOLD", "0.33")
        assert AppConfig().detection.score_threshold == pytest.approx(0.33)


class TestExceptions:
    def test_carries_status_and_code(self) -> None:
        from measurecv.core.exceptions import CalibrationError

        error = CalibrationError("bad board", views=3)
        assert error.status_code == 422
        assert error.code == "calibration_error"
        assert error.to_dict()["context"] == {"views": 3}

    def test_all_inherit_from_root(self) -> None:
        from measurecv.core import exceptions

        for name in exceptions.__all__:
            cls = getattr(exceptions, name)
            assert issubclass(cls, MeasureCVError)


class TestTiming:
    def test_stage_timer_records_stages(self) -> None:
        timer = StageTimer()
        with timer.stage("detect"):
            pass
        timings = timer.finalise()
        assert "detect" in timings
        assert "total" in timings

    def test_rolling_stats_percentiles(self) -> None:
        stats = RollingStats(window=100)
        for value in range(1, 101):
            stats.add(float(value))
        snapshot = stats.snapshot()
        assert snapshot["count"] == 100
        assert snapshot["p50"] == pytest.approx(50.0, abs=2.0)
        assert snapshot["p95"] == pytest.approx(95.0, abs=2.0)

    def test_rolling_stats_empty(self) -> None:
        assert RollingStats().snapshot()["count"] == 0


class TestDetection:
    def test_serialisation(self) -> None:
        detection = Detection(
            bbox=BoundingBox(1.234, 2.345, 10.0, 20.0),
            score=0.876543,
            label_id=3,
            label="cup",
            track_id=7,
        )
        payload = detection.to_dict()
        assert payload["label"] == "cup"
        assert payload["track_id"] == 7
        assert payload["score"] == pytest.approx(0.8765, abs=1e-4)
