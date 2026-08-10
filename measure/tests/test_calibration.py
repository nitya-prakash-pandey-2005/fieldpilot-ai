"""Calibration tests: the camera model, target calibration and scale refinement."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from measurecv.calibration.board import calibrate_from_images, detect_board, make_object_points
from measurecv.calibration.intrinsics import (
    CameraIntrinsics,
    IntrinsicsSource,
    intrinsics_from_exif,
    intrinsics_from_fov,
)
from measurecv.calibration.resolver import IntrinsicsResolver, undistort_image
from measurecv.calibration.scale import (
    ScaleCorrection,
    estimate_scale_correction,
    scale_from_reference_dimension,
)
from measurecv.core.config import CalibrationConfig
from measurecv.core.exceptions import CalibrationError
from measurecv.core.types import Measured, Unit


class TestCameraIntrinsics:
    def test_fov_round_trip(self) -> None:
        k = intrinsics_from_fov(1920, 1080, hfov_deg=65.0)
        assert k.hfov_deg == pytest.approx(65.0, abs=1e-9)
        assert k.source is IntrinsicsSource.ASSUMED_FOV
        assert k.focal_uncertainty == pytest.approx(0.15)

    def test_k_inverse_is_exact(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        np.testing.assert_allclose(k.K @ k.K_inv, np.eye(3), atol=1e-12)

    def test_backproject_project_round_trip(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        u = np.array([100.0, 320.0, 500.0])
        v = np.array([80.0, 240.0, 400.0])
        z = np.array([1.5, 3.0, 7.25])

        points = k.backproject(u, v, z)
        pixels = k.project(points)

        np.testing.assert_allclose(pixels[:, 0], u, atol=1e-9)
        np.testing.assert_allclose(pixels[:, 1], v, atol=1e-9)

    def test_scaling_preserves_field_of_view(self) -> None:
        """Resizing an image cannot change what the camera sees."""
        k = intrinsics_from_fov(1600, 1200, 62.0)
        scaled = k.scaled(800, 600)

        assert scaled.hfov_deg == pytest.approx(k.hfov_deg, abs=0.05)
        assert scaled.fx == pytest.approx(k.fx / 2, rel=1e-9)

    def test_scaling_uses_pixel_centre_convention(self) -> None:
        k = CameraIntrinsics(fx=100, fy=100, cx=49.5, cy=49.5, width=100, height=100)
        scaled = k.scaled(50, 50)
        # (49.5 + 0.5) * 0.5 - 0.5 = 24.5, the centre of a 50 px image.
        assert scaled.cx == pytest.approx(24.5)

    def test_crop_shifts_principal_point_only(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        cropped = k.cropped(100, 50, 400, 300)
        assert cropped.fx == k.fx
        assert cropped.cx == pytest.approx(k.cx - 100)
        assert cropped.cy == pytest.approx(k.cy - 50)

    def test_rejects_nonsense_focal(self) -> None:
        with pytest.raises(CalibrationError):
            CameraIntrinsics(fx=-1, fy=100, cx=50, cy=50, width=100, height=100)

    def test_rejects_implausible_principal_point(self) -> None:
        """A principal point far outside the frame means a unit or ordering
        mistake, which would silently skew every back-projection."""
        with pytest.raises(CalibrationError, match="principal point"):
            CameraIntrinsics(fx=100, fy=100, cx=99999, cy=50, width=640, height=480)

    def test_pixel_area_scales_with_depth_squared(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        near = k.pixel_solid_angle_area(np.array([1.0]))[0]
        far = k.pixel_solid_angle_area(np.array([2.0]))[0]
        assert far / near == pytest.approx(4.0)

    def test_serialisation_round_trip(self, tmp_path) -> None:
        k = CameraIntrinsics(
            fx=612.3,
            fy=613.1,
            cx=319.5,
            cy=239.5,
            width=640,
            height=480,
            distortion=np.array([-0.12, 0.03, 0.001, -0.002, 0.0]),
            source=IntrinsicsSource.CALIBRATED,
            focal_uncertainty=0.012,
        )
        path = tmp_path / "calib.json"
        k.save(path)
        loaded = CameraIntrinsics.load(path)

        assert loaded.fx == pytest.approx(k.fx)
        assert loaded.source is IntrinsicsSource.CALIBRATED
        np.testing.assert_allclose(loaded.distortion, k.distortion)

    def test_load_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(CalibrationError, match="not found"):
            CameraIntrinsics.load(tmp_path / "nope.json")


class TestExif:
    def test_35mm_equivalent(self) -> None:
        """A 26 mm-equivalent phone lens on a 4000x3000 sensor."""
        k = intrinsics_from_exif({"FocalLengthIn35mmFilm": 26}, 4000, 3000)
        assert k is not None
        diagonal = np.hypot(4000, 3000)
        assert k.fx == pytest.approx(26 * diagonal / np.hypot(36.0, 24.0))
        assert k.source is IntrinsicsSource.METADATA

    def test_focal_plane_resolution_path(self) -> None:
        k = intrinsics_from_exif(
            {"FocalLength": 50.0, "FocalPlaneXResolution": 3000.0, "FocalPlaneResolutionUnit": 2},
            6000,
            4000,
        )
        assert k is not None
        assert k.fx > 0

    def test_insufficient_metadata_returns_none(self) -> None:
        """A bare focal length with no sensor size must not be guessed at."""
        assert intrinsics_from_exif({"FocalLength": 50.0}, 4000, 3000) is None
        assert intrinsics_from_exif({}, 640, 480) is None

    def test_garbage_values_return_none(self) -> None:
        assert intrinsics_from_exif({"FocalLengthIn35mmFilm": "abc"}, 640, 480) is None


class TestResolver:
    def test_falls_back_to_assumed_fov(self) -> None:
        resolver = IntrinsicsResolver(CalibrationConfig(default_hfov_deg=55.0))
        k = resolver.resolve(640, 480)
        assert k.source is IntrinsicsSource.ASSUMED_FOV
        assert k.hfov_deg == pytest.approx(55.0)

    def test_prefers_profile_over_exif(self, tmp_path) -> None:
        profile = intrinsics_from_fov(640, 480, 50.0)
        path = tmp_path / "p.json"
        profile.save(path)

        resolver = IntrinsicsResolver(CalibrationConfig(profile=path))
        resolved = resolver.resolve(640, 480, exif={"FocalLengthIn35mmFilm": 26})

        assert resolved.fx == pytest.approx(profile.fx)

    def test_rescales_profile_to_frame_size(self, tmp_path) -> None:
        profile = intrinsics_from_fov(1280, 960, 60.0)
        path = tmp_path / "p.json"
        profile.save(path)

        resolver = IntrinsicsResolver(CalibrationConfig(profile=path))
        resolved = resolver.resolve(640, 480)

        assert resolved.fx == pytest.approx(profile.fx / 2, rel=1e-9)

    def test_refuses_aspect_ratio_change(self, tmp_path) -> None:
        """A different aspect ratio implies a sensor crop, which scaling cannot
        recover -- silently stretching would introduce a systematic error."""
        profile = intrinsics_from_fov(1280, 960, 60.0)  # 4:3
        path = tmp_path / "p.json"
        profile.save(path)
        resolver = IntrinsicsResolver(CalibrationConfig(profile=path))

        with pytest.raises(CalibrationError, match="aspect ratio"):
            resolver.resolve(1920, 1080)  # 16:9

    def test_override_wins(self) -> None:
        resolver = IntrinsicsResolver(CalibrationConfig())
        override = intrinsics_from_fov(640, 480, 30.0)
        assert resolver.resolve(640, 480, override=override).fx == pytest.approx(override.fx)


class TestUndistort:
    def test_no_op_without_distortion(self) -> None:
        k = intrinsics_from_fov(320, 240, 60.0)
        image = np.zeros((240, 320, 3), np.uint8)
        out, updated = undistort_image(image, k)
        assert out is image
        assert updated is k

    def test_produces_rectified_model(self) -> None:
        k = CameraIntrinsics(
            fx=300,
            fy=300,
            cx=159.5,
            cy=119.5,
            width=320,
            height=240,
            distortion=np.array([-0.25, 0.08, 0.0, 0.0, 0.0]),
        )
        image = np.full((240, 320, 3), 128, np.uint8)
        out, updated = undistort_image(image, k)

        assert out.shape == image.shape
        assert not updated.has_distortion
        assert updated.metadata.get("rectified") is True


def _render_chessboard(
    intrinsics: CameraIntrinsics,
    board_shape: tuple[int, int],
    square_m: float,
    rvec: np.ndarray,
    tvec: np.ndarray,
) -> np.ndarray:
    """Render a chessboard by projecting its squares with a known pose.

    Rendering rather than shipping fixture photos keeps the test hermetic and
    lets the *true* intrinsics be asserted against the recovered ones.
    """
    cols, rows = board_shape
    image = np.full((intrinsics.height, intrinsics.width, 3), 255, np.uint8)

    # Squares span one extra row/column beyond the inner corners.
    for i in range(cols + 1):
        for j in range(rows + 1):
            if (i + j) % 2 == 0:
                continue
            corners = np.array(
                [
                    [(i - 1) * square_m, (j - 1) * square_m, 0.0],
                    [i * square_m, (j - 1) * square_m, 0.0],
                    [i * square_m, j * square_m, 0.0],
                    [(i - 1) * square_m, j * square_m, 0.0],
                ],
                dtype=np.float64,
            )
            projected, _ = cv2.projectPoints(
                corners, rvec, tvec, intrinsics.K, intrinsics.distortion
            )
            cv2.fillConvexPoly(image, projected.reshape(-1, 2).astype(np.int32), (0, 0, 0))
    return image


class TestBoardCalibration:
    @pytest.fixture
    def truth(self) -> CameraIntrinsics:
        return CameraIntrinsics(fx=700.0, fy=700.0, cx=319.5, cy=239.5, width=640, height=480)

    def test_detects_rendered_board(self, truth) -> None:
        board_shape, square = (9, 6), 0.025
        image = _render_chessboard(
            truth,
            board_shape,
            square,
            np.array([0.05, 0.02, 0.01]),
            np.array([-0.10, -0.07, 0.55]),
        )
        found = detect_board(image, board_shape, square)
        assert found is not None
        obj, img = found
        assert obj.shape[0] == 9 * 6
        assert img.shape == (54, 2)

    def test_recovers_known_intrinsics(self, truth) -> None:
        """The end-to-end guarantee: calibration must recover the true focal
        length from rendered views of a board with a known pose."""
        board_shape, square = (9, 6), 0.025
        poses = [
            (np.array([0.0, 0.0, 0.0]), np.array([-0.10, -0.07, 0.50])),
            (np.array([0.35, 0.0, 0.0]), np.array([-0.10, -0.05, 0.55])),
            (np.array([-0.35, 0.0, 0.0]), np.array([-0.10, -0.09, 0.55])),
            (np.array([0.0, 0.40, 0.0]), np.array([-0.08, -0.07, 0.52])),
            (np.array([0.0, -0.40, 0.0]), np.array([-0.12, -0.07, 0.52])),
            (np.array([0.25, 0.25, 0.1]), np.array([-0.11, -0.06, 0.58])),
            (np.array([-0.25, 0.25, -0.1]), np.array([-0.09, -0.08, 0.58])),
            (np.array([0.2, -0.3, 0.15]), np.array([-0.10, -0.06, 0.60])),
            (np.array([-0.2, -0.2, 0.05]), np.array([-0.11, -0.08, 0.48])),
        ]
        images = [
            _render_chessboard(truth, board_shape, square, rvec, tvec) for rvec, tvec in poses
        ]

        result = calibrate_from_images(
            images, board_shape, square, min_views=6, max_rms_error_px=2.0
        )

        assert result.intrinsics.fx == pytest.approx(truth.fx, rel=0.03)
        assert result.intrinsics.cx == pytest.approx(truth.cx, abs=15.0)
        assert result.intrinsics.source is IntrinsicsSource.CALIBRATED
        # A good calibration must claim a tighter focal uncertainty than a guess.
        assert result.intrinsics.focal_uncertainty < 0.05

    def test_rejects_too_few_views(self) -> None:
        images = [np.zeros((480, 640, 3), np.uint8)] * 3
        with pytest.raises(CalibrationError, match="at least"):
            calibrate_from_images(images, (9, 6), 0.025, min_views=8)

    def test_reports_undetected_boards(self) -> None:
        images = [np.full((480, 640, 3), 128, np.uint8)] * 10
        with pytest.raises(CalibrationError, match="detected in only"):
            calibrate_from_images(images, (9, 6), 0.025, min_views=8)

    def test_object_points_grid(self) -> None:
        points = make_object_points((4, 3), 0.02)
        assert points.shape == (12, 3)
        assert np.allclose(points[:, 2], 0.0)
        assert points[:, :2].max() == pytest.approx(0.06)


class TestScaleCorrection:
    def test_single_observation(self) -> None:
        correction = estimate_scale_correction([0.090], [0.0856])
        assert correction.factor == pytest.approx(0.0856 / 0.090, rel=1e-9)
        assert correction.sigma > 0

    def test_least_squares_over_multiple(self) -> None:
        truth = [0.0856, 0.297, 0.210]
        measured = [t / 0.95 for t in truth]  # a uniform 5% overestimate
        correction = estimate_scale_correction(measured, truth)
        assert correction.factor == pytest.approx(0.95, rel=1e-6)
        assert correction.residual_rms < 1e-9

    def test_rejects_outlier_observation(self) -> None:
        truth = [0.0856, 0.297, 0.210, 0.100]
        measured = [0.090, 0.312, 0.221, 5.0]  # last is a mis-identified object
        correction = estimate_scale_correction(measured, truth)
        assert correction.n_observations == 3
        assert 0.9 < correction.factor < 1.0

    def test_applies_correct_power_per_quantity(self) -> None:
        correction = ScaleCorrection(factor=0.9, sigma=0.01, n_observations=3)
        length = Measured(1.0, 0.05, Unit.METRE)
        area = Measured(1.0, 0.05, Unit.SQUARE_METRE)
        volume = Measured(1.0, 0.05, Unit.CUBIC_METRE)

        assert correction.apply_length(length).value == pytest.approx(0.9)
        assert correction.apply_area(area).value == pytest.approx(0.81)
        assert correction.apply_volume(volume).value == pytest.approx(0.729)

    def test_uncertainty_grows_with_power(self) -> None:
        correction = ScaleCorrection(factor=1.0, sigma=0.02, n_observations=2)
        base = Measured(1.0, 0.0, Unit.METRE)
        assert correction.apply_volume(base).sigma > correction.apply_length(base).sigma

    def test_rejects_implausible_factor(self) -> None:
        with pytest.raises(CalibrationError, match="implausible"):
            ScaleCorrection(factor=50.0, sigma=0.1, n_observations=1)

    def test_named_reference(self) -> None:
        correction = scale_from_reference_dimension(0.090, "credit_card_long")
        assert correction.factor == pytest.approx(0.0856 / 0.090, rel=1e-6)
        assert correction.reference == "credit_card_long"

    def test_unknown_reference_lists_options(self) -> None:
        with pytest.raises(CalibrationError) as exc:
            scale_from_reference_dimension(0.1, "banana")
        assert "available" in exc.value.context

    def test_mismatched_input_lengths(self) -> None:
        with pytest.raises(CalibrationError, match="equal length"):
            estimate_scale_correction([1.0, 2.0], [1.0])
