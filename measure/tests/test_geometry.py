"""Geometry tests, asserted against analytic ground truth.

These are the tests that actually protect measurement accuracy. Each one builds
a shape whose true dimensions are known in closed form and checks the fitted
result against them, rather than against a previously recorded output.
"""

from __future__ import annotations

import numpy as np
import pytest

from measurecv.core.config import MeasurementConfig
from measurecv.core.exceptions import DegenerateGeometryError, InsufficientDataError
from measurecv.core.types import DepthMap, InstanceMask, Plane, PointCloud
from measurecv.geometry.backproject import (
    backproject_mask,
    depth_edge_mask,
    estimate_boundary_shrink,
    largest_component,
    robust_depth_gate,
    statistical_outlier_filter,
)
from measurecv.geometry.hull import closed_hull_volume, ellipsoid_volume, trim_to_core
from measurecv.geometry.obb import (
    fit_ground_aligned_box,
    fit_pca_box,
    min_area_rect,
    principal_axes,
    trimmed_extent,
)
from measurecv.geometry.plane import (
    SupportFrame,
    estimate_support_plane,
    fit_plane_lsq,
    fit_plane_ransac,
)
from measurecv.geometry.uncertainty import (
    ErrorBudget,
    effective_sample_size,
    extent_uncertainty,
    product_uncertainty,
)


class TestMinAreaRect:
    @pytest.mark.parametrize("angle_deg", [0.0, 17.0, 31.0, 45.0, 73.0, 120.0])
    def test_recovers_rotated_rectangle(self, angle_deg: float, rng) -> None:
        """A rotating-calipers fit must be exact at any orientation."""
        w, h = 0.40, 0.25
        theta = np.deg2rad(angle_deg)
        rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        points = rng.uniform(-0.5, 0.5, size=(4000, 2)) * np.array([w, h])
        points = points @ rot.T + np.array([1.3, -0.7])

        rect = min_area_rect(points)

        assert rect.extents[0] == pytest.approx(w, abs=0.006)
        assert rect.extents[1] == pytest.approx(h, abs=0.006)
        assert rect.extents[0] >= rect.extents[1], "longer side must be reported first"

    def test_area_matches_extents(self, rng) -> None:
        points = rng.uniform(0, 1, size=(500, 2)) * np.array([2.0, 0.5])
        rect = min_area_rect(points)
        assert rect.area == pytest.approx(rect.extents[0] * rect.extents[1], rel=1e-6)

    def test_hull_area_bounds_rect_area(self, rng) -> None:
        """The convex footprint can never exceed its bounding rectangle."""
        points = rng.normal(size=(300, 2))
        rect = min_area_rect(points)
        assert rect.hull_area <= rect.area * 1.0001

    def test_circle_rectangularity(self, rng) -> None:
        """A disc fills pi/4 of its bounding square -- a shape-classification
        signal the volume estimator relies on."""
        angles = rng.uniform(0, 2 * np.pi, 4000)
        radii = np.sqrt(rng.uniform(0, 1, 4000))
        points = np.stack([radii * np.cos(angles), radii * np.sin(angles)], axis=1)
        rect = min_area_rect(points)
        assert rect.hull_area / rect.area == pytest.approx(np.pi / 4, abs=0.03)

    def test_rejects_too_few_points(self) -> None:
        with pytest.raises(DegenerateGeometryError):
            min_area_rect(np.array([[0.0, 0.0], [1.0, 1.0]]))


class TestPlaneFitting:
    def test_lsq_recovers_known_plane(self, rng) -> None:
        normal = np.array([0.2, -0.95, 0.15])
        normal /= np.linalg.norm(normal)
        d = 1.7
        points = rng.uniform(-2, 2, size=(2000, 3))
        points -= np.outer(points @ normal + d, normal)

        plane = fit_plane_lsq(points)

        assert abs(abs(float(plane.normal @ normal)) - 1.0) < 1e-6
        assert abs(abs(plane.d) - d) < 1e-6
        assert plane.rms_error < 1e-9

    def test_ransac_rejects_wall_via_gravity_prior(self, rng) -> None:
        """A large vertical surface must not be mistaken for the floor.

        The wall here has more points than the floor, so without the prior
        RANSAC would prefer it -- and every height would then be measured from
        the wrong datum.
        """
        floor = rng.uniform(-2, 2, size=(1500, 3))
        floor[:, 1] = 1.4
        floor[:, 2] = np.abs(floor[:, 2]) + 1.0

        wall = rng.uniform(-2, 2, size=(4000, 3))
        wall[:, 2] = 3.0

        cloud = PointCloud(np.vstack([floor, wall]))
        plane = estimate_support_plane(cloud, gravity_prior_deg=35.0)

        assert plane is not None
        assert abs(float(plane.normal @ np.array([0.0, -1.0, 0.0]))) > 0.98
        assert plane.d == pytest.approx(1.4, abs=0.02)

    def test_normal_points_up(self, ground_scene_cloud) -> None:
        """Sign convention: positive signed distance means above the surface."""
        plane = estimate_support_plane(ground_scene_cloud["cloud"])
        assert plane is not None
        assert float(plane.normal @ np.array([0.0, -1.0, 0.0])) > 0

        above = np.array([[0.0, 0.4, 3.0]])  # 1.0 m above a floor at y=1.4
        assert float(plane.signed_distance(above)[0]) > 0

    def test_returns_none_without_a_plane(self, rng) -> None:
        blob = PointCloud(rng.normal(scale=0.5, size=(1000, 3)) + np.array([0, 0, 3.0]))
        assert estimate_support_plane(blob, min_inlier_ratio=0.9) is None

    def test_lsq_rejects_non_planar_points(self, rng) -> None:
        with pytest.raises(DegenerateGeometryError):
            fit_plane_lsq(rng.normal(size=(500, 3)))

    def test_ransac_handles_outliers(self, rng) -> None:
        inliers = rng.uniform(-1, 1, size=(1000, 3))
        inliers[:, 1] = 2.0
        outliers = rng.uniform(-3, 3, size=(400, 3))
        points = np.vstack([inliers, outliers])

        plane = fit_plane_ransac(points, distance_threshold=0.05, min_inlier_ratio=0.3)

        assert plane is not None
        assert abs(abs(plane.d) - 2.0) < 0.05


class TestSupportFrame:
    def test_round_trip(self, rng) -> None:
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)
        points = rng.uniform(-2, 2, size=(100, 3))

        recovered = frame.to_camera(frame.to_world(points))

        np.testing.assert_allclose(recovered, points, atol=1e-9)

    def test_world_z_is_height_above_plane(self) -> None:
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)
        # y = 0.4 is 1.0 m above a floor at y = 1.4 (y points down).
        world = frame.to_world(np.array([[0.5, 0.4, 3.0]]))
        assert world[0, 2] == pytest.approx(1.0, abs=1e-9)

    def test_rotation_is_orthonormal(self) -> None:
        normal = np.array([0.1, -0.98, 0.17])
        plane = Plane(normal=normal / np.linalg.norm(normal), d=1.2)
        frame = SupportFrame.from_plane(plane)

        np.testing.assert_allclose(frame.rotation @ frame.rotation.T, np.eye(3), atol=1e-12)
        assert np.linalg.det(frame.rotation) == pytest.approx(1.0, abs=1e-12)


class TestOrientedBox:
    def _cuboid_surface(self, rng, dims, yaw_deg=0.0, n=8000):
        """Points on the visible faces of a cuboid standing on z=0."""
        length, width, height = dims
        u = rng.random((n, 3))
        face = rng.integers(0, 3, n)
        u[face == 0, 0] = np.round(u[face == 0, 0])
        u[face == 1, 1] = np.round(u[face == 1, 1])
        u[face == 2, 2] = 1.0
        points = (u - np.array([0.5, 0.5, 0.0])) * np.array([length, width, height])

        theta = np.deg2rad(yaw_deg)
        rot = np.array(
            [
                [np.cos(theta), -np.sin(theta), 0],
                [np.sin(theta), np.cos(theta), 0],
                [0, 0, 1],
            ]
        )
        return points @ rot.T

    @pytest.mark.parametrize("yaw", [0.0, 20.0, 55.0])
    def test_ground_aligned_box_recovers_cuboid(self, rng, yaw: float) -> None:
        dims = (0.30, 0.20, 0.45)
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)

        world = self._cuboid_surface(rng, dims, yaw)
        camera = frame.to_camera(world) + np.array([0.0, 0.0, 0.0])

        box = fit_ground_aligned_box(camera, plane, percentile=0.5)

        assert box.extents[0] == pytest.approx(dims[0], abs=0.008)
        assert box.extents[1] == pytest.approx(dims[1], abs=0.008)
        assert box.extents[2] == pytest.approx(dims[2], abs=0.008)

    def test_ground_aligned_axes_are_right_handed(self, rng) -> None:
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)
        camera = frame.to_camera(self._cuboid_surface(rng, (0.3, 0.2, 0.45), 30.0))

        box = fit_ground_aligned_box(camera, plane)

        assert np.linalg.det(box.axes) == pytest.approx(1.0, abs=1e-9)
        np.testing.assert_allclose(box.axes @ box.axes.T, np.eye(3), atol=1e-9)

    def test_ground_aligned_vertical_axis_is_plane_normal(self, rng) -> None:
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)
        camera = frame.to_camera(self._cuboid_surface(rng, (0.3, 0.2, 0.45), 12.0))

        box = fit_ground_aligned_box(camera, plane)

        np.testing.assert_allclose(box.axes[2], plane.normal, atol=1e-9)

    def test_pca_box_on_axis_aligned_cloud(self, rng) -> None:
        points = rng.uniform(-0.5, 0.5, size=(4000, 3)) * np.array([1.0, 0.4, 0.2])
        points += np.array([0.0, 0.0, 3.0])

        box = fit_pca_box(points, percentile=0.0)

        extents = np.sort(box.extents)[::-1]
        assert extents[0] == pytest.approx(1.0, abs=0.02)
        assert extents[1] == pytest.approx(0.4, abs=0.02)
        assert extents[2] == pytest.approx(0.2, abs=0.02)

    def test_trimming_resists_a_single_outlier(self, rng) -> None:
        """One bad point must not move the extent by its full displacement."""
        points = rng.uniform(-0.5, 0.5, size=(2000, 3)) * np.array([1.0, 0.5, 0.3])
        contaminated = np.vstack([points, np.array([[8.0, 0.0, 0.0]])])

        untrimmed = fit_pca_box(contaminated, percentile=0.0)
        trimmed = fit_pca_box(contaminated, percentile=1.0)

        assert untrimmed.extents.max() > 4.0
        assert trimmed.extents.max() < 1.2

    def test_principal_axes_orthonormal(self, rng) -> None:
        axes, sigmas = principal_axes(rng.normal(size=(500, 3)) * np.array([3, 2, 1]))
        np.testing.assert_allclose(axes @ axes.T, np.eye(3), atol=1e-9)
        assert sigmas[0] >= sigmas[1] >= sigmas[2]


class TestTrimmedExtent:
    def test_matches_minmax_when_percentile_zero(self, rng) -> None:
        values = rng.normal(size=500)
        lo, hi = trimmed_extent(values, percentile=0.0)
        assert lo == values.min()
        assert hi == values.max()

    def test_falls_back_on_degenerate_input(self) -> None:
        values = np.full(5, 2.0)
        lo, hi = trimmed_extent(values, percentile=10.0)
        assert lo == 2.0 and hi == 2.0


class TestFilters:
    def test_robust_depth_gate_keeps_dominant_mode(self) -> None:
        depths = np.concatenate(
            [np.full(900, 2.0) + np.random.default_rng(0).normal(0, 0.01, 900), np.full(100, 9.0)]
        )
        keep = robust_depth_gate(depths, mad_scale=3.0)
        assert keep[:900].sum() > 880
        assert keep[900:].sum() == 0

    def test_depth_gate_accepts_uniform_depth(self) -> None:
        """Zero MAD must not reject everything -- flat surfaces are legitimate."""
        assert robust_depth_gate(np.full(100, 3.0)).all()

    def test_statistical_outlier_removes_flyers(self, rng) -> None:
        cluster = rng.normal(scale=0.02, size=(500, 3))
        flyers = np.array([[3.0, 3.0, 3.0], [-4.0, 1.0, 2.0]])
        points = np.vstack([cluster, flyers])

        keep = statistical_outlier_filter(points, k=12, std_ratio=2.0)

        assert not keep[-2:].any()
        assert keep[:500].sum() > 450

    def test_largest_component_drops_speck(self) -> None:
        mask = np.zeros((100, 100), bool)
        mask[10:60, 10:60] = True  # main blob
        mask[90:95, 90:95] = True  # speck
        cleaned = largest_component(mask, min_ratio=0.15)
        assert cleaned[10:60, 10:60].all()
        assert not cleaned[90:95, 90:95].any()

    def test_largest_component_keeps_significant_second_blob(self) -> None:
        """A genuinely two-part object must not be silently halved."""
        mask = np.zeros((100, 100), bool)
        mask[10:50, 10:50] = True
        mask[60:95, 60:95] = True
        cleaned = largest_component(mask, min_ratio=0.15)
        assert cleaned.sum() == mask.sum()

    def test_depth_edge_mask_finds_step(self) -> None:
        depth = np.full((100, 100), 2.0, np.float32)
        depth[:, 50:] = 5.0
        edges = depth_edge_mask(depth, threshold=0.06, dilate_px=1)
        assert edges[:, 47:53].any()
        assert not edges[:, :40].any()

    def test_boundary_shrink_matches_known_erosion(self) -> None:
        """The estimator must recover a synthetic erosion radius."""
        import cv2

        mask = np.zeros((200, 200), bool)
        mask[50:150, 40:160] = True
        radius = 4
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
        eroded = cv2.erode(mask.astype(np.uint8), kernel).astype(bool)
        rows, cols = np.nonzero(eroded)

        estimated = estimate_boundary_shrink(mask, rows, cols)

        assert estimated == pytest.approx(radius + 1, abs=1.0)

    def test_boundary_shrink_ignores_interior_holes(self) -> None:
        """An interior removal must not be read as a boundary displacement."""
        mask = np.zeros((200, 200), bool)
        mask[50:150, 40:160] = True
        holed = mask.copy()
        holed[90:110, 90:110] = False
        rows, cols = np.nonzero(holed)

        assert estimate_boundary_shrink(mask, rows, cols) < 1.5


class TestBackprojection:
    def test_plate_dimensions_after_compensation(self, fronto_plate) -> None:
        """The headline accuracy check for the filtering stack.

        A flat 500x300 mm plate must come back within a few millimetres once
        the boundary-shrink compensation is applied.
        """
        config = MeasurementConfig(mask_erode_px=2, min_points=100)
        cloud, report = backproject_mask(
            fronto_plate["mask"],
            fronto_plate["depth_map"],
            fronto_plate["intrinsics"],
            config,
        )
        box = fit_pca_box(cloud.points, percentile=0.0)
        extents = np.sort(box.extents)[::-1]

        compensation = (
            2.0
            * (report.boundary_shrink_px - 0.5)
            * fronto_plate["true_depth_m"]
            / fronto_plate["intrinsics"].fx
        )

        assert extents[0] + compensation == pytest.approx(fronto_plate["true_width_m"], abs=0.006)
        assert extents[1] + compensation == pytest.approx(fronto_plate["true_height_m"], abs=0.006)

    def test_raises_when_too_few_points(self, intrinsics) -> None:
        mask = np.zeros((480, 640), bool)
        mask[100:104, 100:104] = True
        depth = DepthMap(np.full((480, 640), 2.0, np.float32))

        with pytest.raises(InsufficientDataError):
            backproject_mask(
                InstanceMask(mask), depth, intrinsics, MeasurementConfig(min_points=500)
            )

    def test_rejects_shape_mismatch(self, intrinsics) -> None:
        mask = InstanceMask(np.ones((100, 100), bool))
        depth = DepthMap(np.full((480, 640), 2.0, np.float32))
        with pytest.raises(ValueError, match="disagree"):
            backproject_mask(mask, depth, intrinsics, MeasurementConfig())

    def test_erosion_skipped_for_thin_objects(self, intrinsics) -> None:
        """A thin object must still be measurable, with a note explaining why."""
        mask = np.zeros((480, 640), bool)
        mask[200:203, 100:500] = True  # 3 px tall
        depth = DepthMap(np.full((480, 640), 2.0, np.float32))

        cloud, report = backproject_mask(
            InstanceMask(mask),
            depth,
            intrinsics,
            MeasurementConfig(mask_erode_px=5, min_points=50, statistical_outlier_k=0),
        )

        assert len(cloud) > 50
        assert any("erosion_skipped" in note for note in report.notes)

    def test_report_records_pixel_counts(self, fronto_plate) -> None:
        _, report = backproject_mask(
            fronto_plate["mask"],
            fronto_plate["depth_map"],
            fronto_plate["intrinsics"],
            MeasurementConfig(min_points=50),
        )
        assert report.initial_px > report.after_erosion_px >= report.after_outlier_px
        assert 0.0 < report.retention <= 1.0


class TestHull:
    def test_closed_hull_volume_of_a_box(self, rng) -> None:
        length, width, height = 0.3, 0.2, 0.45
        plane = Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4)
        frame = SupportFrame.from_plane(plane)

        u = rng.random((6000, 3))
        face = rng.integers(0, 3, 6000)
        u[face == 0, 0] = np.round(u[face == 0, 0])
        u[face == 1, 1] = np.round(u[face == 1, 1])
        u[face == 2, 2] = 1.0
        world = (u - np.array([0.5, 0.5, 0.0])) * np.array([length, width, height])
        camera = frame.to_camera(world)

        volume, footprint = closed_hull_volume(camera, plane, percentile=0.5)

        assert volume == pytest.approx(length * width * height, rel=0.06)
        assert footprint == pytest.approx(length * width, rel=0.06)

    def test_trim_to_core_shrinks_extremes(self, rng) -> None:
        points = rng.normal(size=(1000, 3))
        core = trim_to_core(points, percentile=5.0)
        assert core.shape[0] < points.shape[0]
        assert np.abs(core).max() < np.abs(points).max()

    def test_trim_never_returns_degenerate_set(self, rng) -> None:
        points = rng.normal(size=(9, 3))
        assert trim_to_core(points, percentile=40.0).shape[0] >= 8

    def test_ellipsoid_is_pi_over_six_of_box(self) -> None:
        extents = np.array([0.4, 0.3, 0.2])
        ratio = ellipsoid_volume(extents) / float(np.prod(extents))
        assert ratio == pytest.approx(np.pi / 6, rel=1e-9)


class TestUncertainty:
    def test_effective_sample_size_is_sqrt_n(self) -> None:
        assert effective_sample_size(10000) == pytest.approx(100.0)

    def test_axial_extent_is_less_certain_than_lateral(self) -> None:
        """Depth-direction measurements are genuinely worse; the model must say so."""
        budget = ErrorBudget(depth_scale_sigma=0.05, depth_noise_sigma=0.02, focal_sigma=0.01)
        common = {"depth": 3.0, "focal_px": 550.0, "n_points": 100, "budget": budget}

        lateral = extent_uncertainty(0.5, axis=np.array([1.0, 0.0, 0.0]), **common)
        axial = extent_uncertainty(0.5, axis=np.array([0.0, 0.0, 1.0]), **common)

        assert axial > lateral

    def test_systematic_error_does_not_vanish_with_samples(self) -> None:
        """A scale bias cannot be averaged away -- this is the core guarantee."""
        budget = ErrorBudget(depth_scale_sigma=0.05, depth_noise_sigma=0.0, focal_sigma=0.0)
        common = {
            "depth": 3.0,
            "axis": np.array([1.0, 0.0, 0.0]),
            "focal_px": 550.0,
            "budget": budget,
        }

        few = extent_uncertainty(1.0, n_points=100, **common)
        many = extent_uncertainty(1.0, n_points=10_000_000, **common)

        assert few == pytest.approx(0.05, rel=0.05)
        assert many == pytest.approx(0.05, rel=0.05)

    def test_volume_scale_error_is_three_times_linear(self) -> None:
        """Correlated errors add linearly: a 5% scale error is 15% on volume,
        not the 8.7% independent quadrature would give."""
        values = [0.5, 0.4, 0.3]
        sigmas = [v * 0.05 for v in values]

        _, sigma = product_uncertainty(values, sigmas, shared_relative=0.05)

        volume = float(np.prod(values))
        assert sigma / volume == pytest.approx(0.15, rel=0.02)

    def test_independent_errors_use_quadrature(self) -> None:
        values = [1.0, 1.0]
        sigmas = [0.03, 0.04]
        _, sigma = product_uncertainty(values, sigmas, shared_relative=0.0)
        assert sigma == pytest.approx(0.05, rel=1e-6)

    def test_zero_extent_has_zero_uncertainty(self) -> None:
        budget = ErrorBudget()
        assert (
            extent_uncertainty(
                0.0, depth=2.0, axis=np.array([1.0, 0, 0]), focal_px=500, n_points=10, budget=budget
            )
            == 0.0
        )
