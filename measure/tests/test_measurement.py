"""Measurement engine tests.

The accuracy assertions here compare against analytically derived truth for
synthetic scenes, so a regression in the geometry shows up as a failing number
rather than a changed snapshot.
"""

from __future__ import annotations

import numpy as np
import pytest

from measurecv.calibration.intrinsics import intrinsics_from_fov
from measurecv.calibration.scale import ScaleCorrection
from measurecv.core.config import MeasurementConfig, TrackingConfig
from measurecv.core.types import (
    BoundingBox,
    DepthMap,
    Detection,
    Dimensions,
    InstanceMask,
    Measured,
    MeasurementMethod,
    ObjectMeasurement,
    SceneMeasurement,
    Unit,
)
from measurecv.geometry.backproject import FilterReport
from measurecv.geometry.obb import OrientedBox
from measurecv.geometry.uncertainty import ErrorBudget
from measurecv.measurement.engine import MeasurementEngine, scene_analytics
from measurecv.measurement.estimators import (
    compute_confidence,
    surface_normals,
)
from measurecv.measurement.temporal import TemporalSmoother


def _plate_scene(depth_z: float = 2.0, plate=(0.5, 0.3)):
    """A fronto-parallel plate with exactly known dimensions."""
    width, height = 640, 480
    k = intrinsics_from_fov(width, height, 60.0)
    plate_w, plate_h = plate

    depth = np.full((height, width), 40.0, np.float32)
    uu, vv = np.meshgrid(np.arange(width), np.arange(height))
    x = (uu - k.cx) * depth_z / k.fx
    y = (vv - k.cy) * depth_z / k.fy
    mask = (np.abs(x) <= plate_w / 2) & (np.abs(y) <= plate_h / 2)
    depth[mask] = depth_z

    detection = Detection(bbox=InstanceMask(mask).bbox(), score=0.9, label_id=1, label="plate")
    return k, DepthMap(depth, scale_uncertainty=0.05), InstanceMask(mask), detection


class TestEngineAccuracy:
    def test_measures_a_plate_to_millimetres(self) -> None:
        """A 500x300 mm plate at 2 m must come back within ~1%."""
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        scene = engine.measure_scene([detection], [mask], depth, k)

        assert len(scene.objects) == 1
        dims = scene.objects[0].dimensions
        assert dims is not None
        measured = sorted([dims.length.value, dims.width.value, dims.height.value], reverse=True)
        assert measured[0] == pytest.approx(0.50, abs=0.008)
        assert measured[1] == pytest.approx(0.30, abs=0.008)

    def test_accuracy_holds_across_depths(self) -> None:
        """Relative accuracy must not degrade with distance for a lateral extent."""
        engine = MeasurementEngine(MeasurementConfig(min_points=80, estimate_ground_plane=False))
        for depth_z in (1.5, 3.0, 5.0):
            k, depth, mask, detection = _plate_scene(depth_z)
            scene = engine.measure_scene([detection], [mask], depth, k)
            dims = scene.objects[0].dimensions
            assert dims is not None
            longest = max(dims.length.value, dims.width.value, dims.height.value)
            assert longest == pytest.approx(0.50, rel=0.03), f"failed at {depth_z} m"

    def test_reports_uncertainty_on_every_dimension(self) -> None:
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        dims = engine.measure_scene([detection], [mask], depth, k).objects[0].dimensions

        assert dims is not None
        assert dims.length.sigma > 0
        # The 5% depth-scale uncertainty sets the floor on the error bar.
        assert dims.length.relative_error >= 0.049

    def test_distance_matches_geometry(self) -> None:
        k, depth, mask, detection = _plate_scene(depth_z=3.0)
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        obj = engine.measure_scene([detection], [mask], depth, k).objects[0]

        assert obj.distance is not None
        # The plate is centred, so range to centroid equals Z.
        assert obj.distance.value == pytest.approx(3.0, rel=0.02)

    def test_surface_area_of_a_known_plate(self) -> None:
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        area = engine.measure_scene([detection], [mask], depth, k).objects[0].surface_area

        assert area is not None
        assert area.value == pytest.approx(0.5 * 0.3, rel=0.10)


class TestFailureHandling:
    def test_unmeasurable_object_does_not_fail_the_frame(self) -> None:
        """One bad object must not discard the other nine."""
        k, depth, mask, detection = _plate_scene()
        tiny = np.zeros_like(mask.mask)
        tiny[10:13, 10:13] = True
        tiny_detection = Detection(
            bbox=BoundingBox(10, 10, 13, 13), score=0.6, label_id=2, label="speck"
        )

        engine = MeasurementEngine(MeasurementConfig(min_points=200, estimate_ground_plane=False))
        scene = engine.measure_scene(
            [detection, tiny_detection], [mask, InstanceMask(tiny)], depth, k
        )

        assert len(scene.objects) == 2
        assert scene.objects[0].dimensions is not None
        assert scene.objects[1].dimensions is None
        assert scene.objects[1].confidence == 0.0
        assert any("not measurable" in w for w in scene.objects[1].warnings)

    def test_mismatched_inputs_raise(self) -> None:
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig())
        with pytest.raises(ValueError, match="aligned"):
            engine.measure_scene([detection, detection], [mask], depth, k)

    def test_truncated_object_is_flagged(self) -> None:
        width, height = 640, 480
        k = intrinsics_from_fov(width, height, 60.0)
        mask = np.zeros((height, width), bool)
        mask[100:400, 0:300] = True  # touches the left border
        depth = DepthMap(np.full((height, width), 2.0, np.float32))
        detection = Detection(
            bbox=BoundingBox(0, 100, 300, 400), score=0.9, label_id=1, label="box"
        )

        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))
        obj = engine.measure_scene([detection], [InstanceMask(mask)], depth, k).objects[0]

        assert any("border" in w or "clipped" in w for w in obj.warnings)
        assert obj.confidence < 0.6


class TestScaleCorrectionApplication:
    def test_scales_each_quantity_by_the_right_power(self) -> None:
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        baseline = engine.measure_scene([detection], [mask], depth, k).objects[0]
        corrected = engine.measure_scene(
            [detection],
            [mask],
            depth,
            k,
            scale_correction=ScaleCorrection(factor=0.9, sigma=0.01, n_observations=3),
        ).objects[0]

        assert baseline.dimensions is not None and corrected.dimensions is not None
        assert corrected.dimensions.length.value == pytest.approx(
            baseline.dimensions.length.value * 0.9, rel=1e-6
        )
        assert corrected.surface_area is not None and baseline.surface_area is not None
        assert corrected.surface_area.value == pytest.approx(
            baseline.surface_area.value * 0.81, rel=1e-6
        )

    def test_reference_object_tightens_the_error_bar(self) -> None:
        """Measuring a known object is the point -- it must reduce uncertainty."""
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))

        baseline = engine.measure_scene([detection], [mask], depth, k).objects[0]
        corrected = engine.measure_scene(
            [detection],
            [mask],
            depth,
            k,
            scale_correction=ScaleCorrection(factor=1.0, sigma=0.005, n_observations=5),
        ).objects[0]

        assert baseline.dimensions is not None and corrected.dimensions is not None
        assert (
            corrected.dimensions.length.relative_error < baseline.dimensions.length.relative_error
        )


class TestSurfaceNormals:
    def test_fronto_parallel_plane_normals_face_camera(self) -> None:
        k = intrinsics_from_fov(320, 240, 60.0)
        depth = np.full((240, 320), 3.0, np.float32)

        normals = surface_normals(depth, k)
        unit = normals[120, 160] / np.linalg.norm(normals[120, 160])

        assert abs(abs(unit[2]) - 1.0) < 1e-6

    def test_patch_area_matches_pinhole_formula(self) -> None:
        """|dP/du x dP/dv| must equal Z^2/(fx*fy) for a flat facing surface."""
        k = intrinsics_from_fov(320, 240, 60.0)
        depth = np.full((240, 320), 3.0, np.float32)

        normals = surface_normals(depth, k)
        magnitude = np.linalg.norm(normals[120, 160])

        assert magnitude == pytest.approx(9.0 / (k.fx * k.fy), rel=1e-6)

    def test_slanted_surface_has_larger_area(self) -> None:
        k = intrinsics_from_fov(320, 240, 60.0)
        rows = np.arange(240, dtype=np.float32)[:, None]
        depth = np.repeat(3.0 + rows * 0.01, 320, axis=1).astype(np.float32)

        normals = surface_normals(depth, k)
        flat = 3.0**2 / (k.fx * k.fy)

        assert np.linalg.norm(normals[10, 160]) > flat


class TestConfidence:
    def _box(self, condition: float = 0.5) -> OrientedBox:
        return OrientedBox(
            center=np.zeros(3),
            axes=np.eye(3),
            extents=np.array([1.0, 0.8, 0.5]),
            condition=condition,
        )

    def _report(self, retention: float = 0.9) -> FilterReport:
        return FilterReport(initial_px=1000, after_outlier_px=int(1000 * retention))

    def test_good_inputs_give_high_confidence(self) -> None:
        score, warnings = compute_confidence(
            detection_score=0.95,
            mask_iou=0.95,
            mask_stability=0.95,
            report=self._report(0.9),
            box=self._box(0.5),
            n_points=5000,
            min_points=100,
            truncated=False,
            focal_uncertainty=0.01,
            depth_coverage=0.95,
        )
        assert score > 0.75
        assert warnings == []

    def test_truncation_dominates(self) -> None:
        """A perfect mask on a clipped object is still not a usable measurement."""
        score, warnings = compute_confidence(
            detection_score=0.99,
            mask_iou=0.99,
            mask_stability=0.99,
            report=self._report(1.0),
            box=self._box(0.5),
            n_points=50000,
            min_points=100,
            truncated=True,
            focal_uncertainty=0.01,
            depth_coverage=1.0,
        )
        assert score < 0.75
        assert any("clipped" in w for w in warnings)

    def test_uncalibrated_camera_lowers_confidence(self) -> None:
        calibrated, _ = compute_confidence(
            detection_score=0.9,
            mask_iou=0.9,
            mask_stability=0.9,
            report=self._report(),
            box=self._box(),
            n_points=5000,
            min_points=100,
            truncated=False,
            focal_uncertainty=0.01,
            depth_coverage=0.9,
        )
        assumed, warnings = compute_confidence(
            detection_score=0.9,
            mask_iou=0.9,
            mask_stability=0.9,
            report=self._report(),
            box=self._box(),
            n_points=5000,
            min_points=100,
            truncated=False,
            focal_uncertainty=0.15,
            depth_coverage=0.9,
        )
        assert assumed < calibrated
        assert any("assumed" in w for w in warnings)

    def test_planar_object_warns(self) -> None:
        _, warnings = compute_confidence(
            detection_score=0.9,
            mask_iou=0.9,
            mask_stability=0.9,
            report=self._report(),
            box=self._box(condition=0.001),
            n_points=5000,
            min_points=100,
            truncated=False,
            focal_uncertainty=0.02,
            depth_coverage=0.9,
        )
        assert any("planar" in w for w in warnings)

    def test_score_is_bounded(self) -> None:
        score, _ = compute_confidence(
            detection_score=0.01,
            mask_iou=0.01,
            mask_stability=0.01,
            report=self._report(0.01),
            box=self._box(0.0),
            n_points=1,
            min_points=1000,
            truncated=True,
            focal_uncertainty=0.5,
            depth_coverage=0.01,
        )
        assert 0.0 <= score <= 1.0


class TestTemporalSmoother:
    def _scene(self, value: float, frame: int, track_id: int = 1) -> SceneMeasurement:
        dims = Dimensions(
            length=Measured(value, 0.05, Unit.METRE, MeasurementMethod.GROUND_ALIGNED),
            width=Measured(0.3, 0.03, Unit.METRE),
            height=Measured(0.4, 0.04, Unit.METRE),
        )
        obj = ObjectMeasurement(
            detection=Detection(
                bbox=BoundingBox(0, 0, 10, 10),
                score=0.9,
                label_id=1,
                label="box",
                track_id=track_id,
            ),
            dimensions=dims,
            confidence=0.8,
        )
        return SceneMeasurement(objects=[obj], frame_index=frame)

    def test_ema_converges_to_the_mean(self) -> None:
        smoother = TemporalSmoother(TrackingConfig(smoothing="ema", smoothing_alpha=0.3))
        rng = np.random.default_rng(3)

        for i in range(60):
            scene = smoother.update(self._scene(0.5 + rng.normal(0, 0.02), i))

        assert scene.objects[0].dimensions.length.value == pytest.approx(0.5, abs=0.02)

    def test_systematic_error_floors_the_uncertainty(self) -> None:
        """This is the key guarantee: watching for longer must not imply a
        precision the systematic error budget cannot support."""
        smoother = TemporalSmoother(TrackingConfig(smoothing="ema"), systematic_fraction=0.8)

        for i in range(200):
            scene = smoother.update(self._scene(0.5, i))

        sigma = scene.objects[0].dimensions.length.sigma
        assert sigma == pytest.approx(0.05 * 0.8, rel=0.05)
        assert sigma > 0.03, "sigma must not collapse toward zero"

    def test_median_mode_rejects_a_spike(self) -> None:
        smoother = TemporalSmoother(TrackingConfig(smoothing="median", smoothing_window=9))
        for i in range(8):
            smoother.update(self._scene(0.5, i))
        scene = smoother.update(self._scene(5.0, 8))  # a single wild reading

        assert scene.objects[0].dimensions.length.value == pytest.approx(0.5, abs=0.01)

    def test_untracked_objects_pass_through(self) -> None:
        smoother = TemporalSmoother(TrackingConfig(smoothing="ema"))
        scene = self._scene(0.5, 0)
        scene.objects[0].detection.track_id = None

        result = smoother.update(scene)

        assert result.objects[0].dimensions.length.value == 0.5
        assert not smoother.tracks

    def test_prunes_dead_tracks(self) -> None:
        smoother = TemporalSmoother(TrackingConfig(smoothing="ema"))
        smoother.update(self._scene(0.5, 0, track_id=1))
        smoother.update(self._scene(0.5, 1, track_id=2))
        assert set(smoother.tracks) == {2}

    def test_disabled_smoothing_is_a_no_op(self) -> None:
        smoother = TemporalSmoother(TrackingConfig(smoothing="none"))
        scene = smoother.update(self._scene(0.5, 0))
        assert scene.objects[0].dimensions.length.sigma == 0.05


class TestSceneAnalytics:
    def test_pairwise_distances(self) -> None:
        objects = []
        for i, position in enumerate([np.array([0.0, 0.0, 2.0]), np.array([3.0, 0.0, 2.0])]):
            objects.append(
                ObjectMeasurement(
                    detection=Detection(
                        bbox=BoundingBox(0, 0, 10, 10),
                        score=0.9,
                        label_id=1,
                        label=f"o{i}",
                        track_id=i,
                    ),
                    position=position,
                )
            )
        scene = SceneMeasurement(objects=objects)

        pairs = scene_analytics(scene).pairwise_distances(ErrorBudget())

        assert len(pairs) == 1
        assert pairs[0]["distance"]["value"] == pytest.approx(3.0)

    def test_summary_counts(self) -> None:
        k, depth, mask, detection = _plate_scene()
        engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))
        scene = engine.measure_scene([detection], [mask], depth, k)

        summary = scene_analytics(scene).summary()

        assert summary["objects_detected"] == 1
        assert summary["objects_measured"] == 1
        assert summary["counts_by_label"] == {"plate": 1}
