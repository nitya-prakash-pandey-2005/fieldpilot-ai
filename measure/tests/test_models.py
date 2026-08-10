"""Model-layer tests.

The centrepiece is :class:`TestCanonicalTransform`. Metric3D's
canonical-camera-space conversion is the single line that decides whether the
system reports metres or nonsense, and it fails *silently* -- a depth map that
skips it looks smooth, correctly ordered and entirely plausible while being
wrong by ``f/1000``. It gets a dedicated test with hand-computed expectations.
"""

from __future__ import annotations

import numpy as np
import pytest

from measurecv.calibration.intrinsics import intrinsics_from_fov
from measurecv.core.config import AppConfig, DepthConfig
from measurecv.core.exceptions import ConfigurationError, DepthEstimationError, ModelLoadError
from measurecv.models.depth.metric3d import (
    _canonical_to_metric,
    postprocess_metric3d,
    preprocess_metric3d,
)
from measurecv.models.manager import ModelManager
from measurecv.models.synthetic import (
    SYNTHETIC_CAMERA_HEIGHT_M,
    SyntheticDepthEstimator,
    SyntheticDetector,
    SyntheticSegmenter,
    foreground_mask,
    ground_depth,
)


class TestCanonicalTransform:
    """The canonical -> metric conversion for Metric3D."""

    def test_identity_at_canonical_focal(self) -> None:
        """A camera whose focal already equals the canonical one needs no change."""
        depth = np.full((4, 4), 5.0, np.float32)
        out = _canonical_to_metric(depth, focal_px=1000.0, resize_scale=1.0, canonical_focal=1000.0)
        np.testing.assert_allclose(out, depth)

    def test_scales_linearly_with_focal_length(self) -> None:
        """This is the failure mode: skipping the transform on a 1400 px focal
        under-reports every depth by 40%."""
        depth = np.full((4, 4), 5.0, np.float32)
        out = _canonical_to_metric(depth, focal_px=1400.0, resize_scale=1.0, canonical_focal=1000.0)
        np.testing.assert_allclose(out, depth * 1.4, rtol=1e-6)

    def test_accounts_for_the_resize(self) -> None:
        """The effective focal is the *post-resize* one, not the original."""
        depth = np.full((2, 2), 3.0, np.float32)
        out = _canonical_to_metric(depth, focal_px=2000.0, resize_scale=0.5, canonical_focal=1000.0)
        # 2000 * 0.5 / 1000 = 1.0
        np.testing.assert_allclose(out, depth, rtol=1e-6)

    def test_rejects_invalid_focal(self) -> None:
        with pytest.raises(DepthEstimationError):
            _canonical_to_metric(np.ones((2, 2), np.float32), 0.0, 1.0, 1000.0)

    @pytest.mark.parametrize("focal,scale", [(500.0, 1.0), (1500.0, 0.4), (900.0, 1.2)])
    def test_is_invertible(self, focal: float, scale: float) -> None:
        depth = np.linspace(1, 10, 16, dtype=np.float32).reshape(4, 4)
        metric = _canonical_to_metric(depth, focal, scale, 1000.0)
        recovered = metric * 1000.0 / (focal * scale)
        np.testing.assert_allclose(recovered, depth, rtol=1e-5)


class TestMetric3DPreprocessing:
    def test_fits_inside_the_network_window(self) -> None:
        image = np.zeros((1080, 1920, 3), np.uint8)
        array, scale, pad = preprocess_metric3d(image, (616, 1064))

        assert array.shape == (3, 616, 1064)
        assert scale == pytest.approx(min(616 / 1080, 1064 / 1920))
        assert all(p >= 0 for p in pad)

    def test_preserves_aspect_ratio(self) -> None:
        """An anisotropic resize would change fx and fy differently and break
        the single-scalar canonical transform."""
        image = np.zeros((480, 640, 3), np.uint8)
        _, _scale, (top, bottom, left, right) = preprocess_metric3d(image, (616, 1064))

        content_h = 616 - top - bottom
        content_w = 1064 - left - right
        assert content_w / content_h == pytest.approx(640 / 480, rel=0.01)

    def test_pads_with_dataset_mean_not_black(self) -> None:
        """Black padding creates an artificial edge whose depth artefacts bleed
        into the real image region."""
        image = np.full((100, 100, 3), 128, np.uint8)
        array, _, (_top, _, left, _) = preprocess_metric3d(image, (616, 1064))
        if left > 2:
            corner = array[:, 0, 0]
            # Mean padding normalises to ~0, black would be strongly negative.
            assert np.all(np.abs(corner) < 0.1)

    def test_postprocess_round_trip(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        config = DepthConfig()
        image = np.zeros((480, 640, 3), np.uint8)
        _, scale, pad = preprocess_metric3d(image, config.input_size)

        canonical = np.full(config.input_size, 2.0, np.float32)
        metric = postprocess_metric3d(canonical, pad, (480, 640), k, scale, config)

        assert metric.shape == (480, 640)
        expected = 2.0 * (k.fx * scale) / config.canonical_focal
        assert float(np.median(metric)) == pytest.approx(expected, rel=0.02)

    def test_postprocess_clips_out_of_range(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        config = DepthConfig(max_depth_m=10.0, min_depth_m=0.5)
        image = np.zeros((480, 640, 3), np.uint8)
        _, scale, pad = preprocess_metric3d(image, config.input_size)

        canonical = np.full(config.input_size, 1e6, np.float32)
        metric = postprocess_metric3d(canonical, pad, (480, 640), k, scale, config)

        assert metric.max() <= 10.0


class TestMetric3DBackendWiring:
    """Exercise the real Metric3D backend's pure-Python paths.

    Weight loading needs a network download, but preprocessing does not -- and
    that is where a refactor is most likely to leave a dangling reference.
    Regression: ``_preprocess`` once returned undefined names left over from a
    signature change, which would have raised ``NameError`` on the primary
    depth path while every synthetic-backend test kept passing.
    """

    @pytest.fixture
    def estimator(self):
        pytest.importorskip("torch")
        from measurecv.models.depth.metric3d import Metric3DDepthEstimator

        return Metric3DDepthEstimator(DepthConfig())

    def test_preprocess_runs_without_weights(self, estimator) -> None:
        image = np.zeros((480, 640, 3), np.uint8)

        tensor, scale, pad = estimator._preprocess(image)

        assert tuple(tensor.shape) == (1, 3, 616, 1064)
        # A small image is *upscaled* to fill the canonical window, so the
        # factor exceeds 1 here. What matters is that the same factor reaches
        # the canonical-to-metric conversion, not its direction.
        assert scale == pytest.approx(min(616 / 480, 1064 / 640))
        assert len(pad) == 4 and all(isinstance(p, int) for p in pad)

    def test_preprocess_pad_matches_window(self, estimator) -> None:
        tensor, _, (top, bottom, left, right) = estimator._preprocess(
            np.zeros((720, 1280, 3), np.uint8)
        )
        assert tensor.shape[2] - top - bottom > 0
        assert tensor.shape[3] - left - right > 0

    def test_estimate_rejects_mismatched_intrinsics(self, estimator) -> None:
        """Metric scale depends on the focal matching the actual frame, so a
        mismatch must fail rather than silently rescale."""
        estimator._loaded = True  # skip the download; the guard runs first
        with pytest.raises(DepthEstimationError, match="intrinsics are for"):
            estimator.estimate(
                np.zeros((480, 640, 3), np.uint8), intrinsics_from_fov(1920, 1080, 60.0)
            )

    def test_name_reports_model(self, estimator) -> None:
        assert "metric3d" in estimator.name


class TestSyntheticBackends:
    def test_ground_depth_matches_pinhole_geometry(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        depth = ground_depth(k, SYNTHETIC_CAMERA_HEIGHT_M)

        row = 400
        expected = k.fy * SYNTHETIC_CAMERA_HEIGHT_M / (row - k.cy)
        assert depth[row, 320] == pytest.approx(expected, rel=1e-5)

    def test_no_ground_above_horizon(self) -> None:
        k = intrinsics_from_fov(640, 480, 60.0)
        depth = ground_depth(k, 1.4)
        assert np.all(depth[: int(k.cy), :] == 0.0)

    def test_foreground_mask_finds_the_object(self) -> None:
        image = np.full((100, 100, 3), 90, np.uint8)
        image[30:60, 40:70] = (220, 60, 40)
        mask = foreground_mask(image)
        assert mask[30:60, 40:70].all()
        assert mask.sum() == 30 * 30

    def test_detector_finds_blobs(self) -> None:
        image = np.full((200, 200, 3), 90, np.uint8)
        image[30:70, 30:70] = (220, 60, 40)
        image[120:170, 120:180] = (40, 200, 90)

        detections = SyntheticDetector().detect(image)

        assert len(detections) == 2
        assert all(d.score > 0.5 for d in detections)

    def test_segmenter_respects_box(self) -> None:
        from measurecv.core.types import BoundingBox

        image = np.full((200, 200, 3), 90, np.uint8)
        image[30:70, 30:70] = (220, 60, 40)
        image[120:170, 120:180] = (40, 200, 90)

        masks = SyntheticSegmenter().segment(image, [BoundingBox(30, 30, 70, 70)])

        assert len(masks) == 1
        assert masks[0].mask.sum() == 40 * 40
        assert not masks[0].mask[120:170, 120:180].any()

    def test_depth_places_object_on_the_plane(self) -> None:
        """The synthetic scene must be metrically self-consistent, or the
        end-to-end accuracy tests would be meaningless."""
        k = intrinsics_from_fov(640, 480, 60.0)
        image = np.full((480, 640, 3), 90, np.uint8)
        image[300:400, 280:360] = (220, 60, 40)

        depth = SyntheticDepthEstimator().estimate(image, k)

        expected = k.fy * SYNTHETIC_CAMERA_HEIGHT_M / (400 - k.cy)
        assert depth.depth[350, 320] == pytest.approx(expected, rel=1e-4)

    def test_depth_map_has_no_invalid_holes(self) -> None:
        k = intrinsics_from_fov(320, 240, 60.0)
        depth = SyntheticDepthEstimator().estimate(np.zeros((240, 320, 3), np.uint8), k)
        assert depth.valid().all()


class TestModelManager:
    def test_builds_synthetic_backends(self) -> None:
        manager = ModelManager(AppConfig().synthetic())
        assert manager.detector.name == "synthetic:detector"
        assert manager.segmenter.name == "synthetic:segmenter"
        assert manager.depth_estimator.name == "synthetic:depth"

    def test_lazy_loading(self) -> None:
        manager = ModelManager(AppConfig().synthetic())
        assert manager.info()["detector"] == {"loaded": False}

        manager.detector.ensure_loaded()
        assert manager.info()["detector"]["loaded"] is True

    def test_unknown_backend_raises(self) -> None:
        config = AppConfig().synthetic()
        config.detection.backend = "nope"  # type: ignore[assignment]
        with pytest.raises(ConfigurationError, match="unknown detection backend"):
            _ = ModelManager(config).detector

    def test_inference_slot_bounds_concurrency(self) -> None:
        config = AppConfig().synthetic()
        config.api.max_concurrent_inferences = 1
        manager = ModelManager(config)

        with manager.inference_slot():
            assert not manager._semaphore.acquire(blocking=False)
        assert manager._semaphore.acquire(blocking=False)

    def test_release_is_idempotent(self) -> None:
        manager = ModelManager(AppConfig().synthetic())
        manager.detector.ensure_loaded()
        manager.release_all()
        manager.release_all()
        assert manager.detector.is_loaded is False

    def test_onnx_backend_requires_path(self) -> None:
        config = AppConfig().synthetic()
        with pytest.raises(Exception, match="onnx_path"):
            config.detection.backend = "onnx"
            AppConfig(**config.model_dump())


class TestRealBackendsUnavailable:
    """Real backends must fail loudly, never degrade to synthetic silently."""

    def test_missing_onnx_path_raises_model_load_error(self) -> None:
        from measurecv.models.detection.onnx_detector import OnnxDetector

        with pytest.raises(ModelLoadError, match="onnx_path"):
            OnnxDetector(AppConfig().detection)
