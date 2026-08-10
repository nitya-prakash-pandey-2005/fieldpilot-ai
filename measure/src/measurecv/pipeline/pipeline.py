"""The measurement pipeline.

Stage order and why it is this order
------------------------------------
``preprocess -> detect -> track -> segment -> depth -> measure``

* **Detect before segment** because SAM 2 is promptable, not a detector. Boxes
  tell it which objects matter, and box-prompted decoding costs one cheap
  decoder pass against a single shared image embedding.
* **Track between detect and segment** so that on frames where detection is
  skipped the motion model can supply prompts, and so identities exist before
  measurements are produced and fused.
* **Depth once per frame, not once per object.** Metric3D is a dense
  whole-image model; running it per crop would be both slower and *less*
  accurate, because cropping changes the effective field of view and the
  canonical transform depends on it.
* **Measure last**, when masks, depth and calibration all exist in the same
  coordinate frame at the same resolution.

Resolution handling
-------------------
Large uploads are downscaled once, up front, and the intrinsics are scaled with
them. This is the only safe place to resize: every later stage assumes masks,
depth and intrinsics share one coordinate frame, and a mismatch there produces
measurements that are wrong by the ratio of the two resolutions with no error
raised anywhere.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.calibration.resolver import IntrinsicsResolver, read_exif, undistort_image
from measurecv.calibration.scale import ScaleCorrection
from measurecv.core.config import AppConfig
from measurecv.core.exceptions import MeasureCVError
from measurecv.core.logging import bind_context, get_logger, unbind_context
from measurecv.core.timing import RollingStats, StageTimer
from measurecv.core.types import Detection, Frame, InstanceMask, SceneMeasurement
from measurecv.measurement.engine import MeasurementEngine
from measurecv.measurement.temporal import TemporalSmoother
from measurecv.models.manager import ModelManager
from measurecv.pipeline.sources import FrameSource, open_source, read_image
from measurecv.tracking.bytetrack import ByteTracker

log = get_logger(__name__)

__all__ = ["FrameArtifacts", "MeasurementPipeline"]


class FrameArtifacts:
    """A frame's measurements plus the intermediates that produced them.

    Masks and the depth map are several megabytes per frame, so they are not
    attached to :class:`SceneMeasurement` (which gets serialised, logged and
    accumulated across a whole video). Callers that genuinely need them --
    the API when asked for mask or depth payloads, the CLI when writing
    visualisations, anyone debugging a suspicious number -- ask for them
    explicitly via :meth:`MeasurementPipeline.measure_frame_full`.
    """

    __slots__ = ("depth_map", "image", "intrinsics", "masks", "scene")

    def __init__(
        self,
        scene: SceneMeasurement,
        masks: list[InstanceMask],
        depth_map: Any,
        image: NDArray[np.uint8],
        intrinsics: CameraIntrinsics,
    ) -> None:
        self.scene = scene
        self.masks = masks
        self.depth_map = depth_map
        #: The *processed* image (possibly downscaled and rectified), which is
        #: the frame the masks and depth actually correspond to.
        self.image = image
        self.intrinsics = intrinsics


class MeasurementPipeline:
    """End-to-end RGB -> metric measurements.

    Thread safety: :meth:`measure_frame` is safe to call concurrently (GPU
    access is bounded by the model manager), but the *stateful* video helpers
    (:meth:`process_video`, :meth:`process_stream`) own a tracker and smoother
    and must not be driven from two threads at once. Use one pipeline instance
    per stream.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        models: ModelManager | None = None,
    ) -> None:
        self._config = config or AppConfig()
        self._models = models or ModelManager(self._config)
        self._engine = MeasurementEngine(
            self._config.measurement,
            plane_every_n_frames=self._config.runtime.ground_plane_every_n_frames,
        )
        self._resolver = IntrinsicsResolver(self._config.calibration)

        self._tracker = ByteTracker(self._config.tracking)
        self._smoother = TemporalSmoother(self._config.tracking)

        self._latency = RollingStats()
        self._frames_processed = 0
        self._scale_correction: ScaleCorrection | None = None
        self._last_detections: list[Detection] = []

        # Cached depth for runtime.depth_every_n_frames. Depth is the most
        # expensive stage and the slowest-changing quantity, so reusing it is
        # the single biggest live-mode saving that does not compromise the
        # accuracy of the depth that *is* computed.
        self._cached_depth: Any = None
        self._cached_depth_shape: tuple[int, int] | None = None
        self._depth_age = 0

    # -- properties --------------------------------------------------------
    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def models(self) -> ModelManager:
        return self._models

    @property
    def resolver(self) -> IntrinsicsResolver:
        return self._resolver

    @property
    def scale_correction(self) -> ScaleCorrection | None:
        return self._scale_correction

    def set_scale_correction(self, correction: ScaleCorrection | None) -> None:
        """Install (or clear) a reference-object scale refinement."""
        self._scale_correction = correction
        if correction is not None:
            log.info("scale_correction_applied", **correction.to_dict())

    def warmup(self) -> None:
        self._models.warmup()

    def reset_state(self) -> None:
        """Clear tracker, temporal and depth-cache state.

        Call between unrelated streams: a cached depth map from a different
        scene would be applied to the new one's masks.
        """
        self._tracker.reset()
        self._smoother.reset()
        self._engine.reset_plane_cache()
        self._last_detections = []
        self._cached_depth = None
        self._cached_depth_shape = None
        self._depth_age = 0

    def stats(self) -> dict[str, Any]:
        return {
            "frames_processed": self._frames_processed,
            "latency_ms": self._latency.snapshot(),
            "active_tracks": self._tracker.active_tracks,
            "models": self._models.info(),
        }

    # -- single-image entry points ----------------------------------------
    def measure_image(
        self,
        image: str | Path | NDArray[np.uint8],
        *,
        intrinsics: CameraIntrinsics | None = None,
        use_exif: bool = True,
    ) -> SceneMeasurement:
        """Measure a single image, given a path or an RGB array."""
        exif: dict[str, Any] = {}
        if isinstance(image, str | Path):
            path = Path(image)
            if use_exif and self._config.calibration.allow_exif:
                exif = read_exif(path)
            array = read_image(path)
            source_id = str(path)
        else:
            array = np.asarray(image)
            source_id = "array"
            if array.ndim != 3 or array.shape[2] != 3:
                raise ValueError(f"expected an (H, W, 3) RGB array, got {array.shape}")

        frame = Frame(image=array, index=0, timestamp=time.time(), source_id=source_id)
        return self.measure_frame(frame, intrinsics=intrinsics, exif=exif, track=False)

    def measure_frame(
        self,
        frame: Frame,
        *,
        intrinsics: CameraIntrinsics | None = None,
        exif: dict[str, Any] | None = None,
        track: bool = False,
        detect: bool = True,
    ) -> SceneMeasurement:
        """Run the full pipeline on one frame.

        Args:
            frame: The input frame.
            intrinsics: Explicit camera model, overriding the resolver ladder.
            exif: EXIF tags, used when no profile or override is available.
            track: Assign track ids and fuse measurements temporally.
            detect: Run detection. When ``False`` the tracker's predicted boxes
                are used instead (see ``runtime.detect_every_n_frames``).

        Returns:
            A :class:`SceneMeasurement`, always at the *original* frame
            resolution regardless of internal downscaling.
        """
        return self.measure_frame_full(
            frame, intrinsics=intrinsics, exif=exif, track=track, detect=detect
        ).scene

    def measure_frame_full(
        self,
        frame: Frame,
        *,
        intrinsics: CameraIntrinsics | None = None,
        exif: dict[str, Any] | None = None,
        track: bool = False,
        detect: bool = True,
    ) -> FrameArtifacts:
        """As :meth:`measure_frame`, but also returns masks and the depth map.

        Note that the returned masks and depth are in the *processed* frame's
        coordinate space, which may be smaller than the input if downscaling
        applied. ``artifacts.image`` is the matching frame.
        """
        timer = StageTimer(sync_gpu=self._models.device.is_cuda)
        started = time.perf_counter()
        bind_context(frame=frame.index, source=frame.source_id)

        try:
            with timer.stage("preprocess"):
                image, camera, resize_scale = self._prepare(frame.image, intrinsics, exif or {})

            with self._models.inference_slot():
                with timer.stage("detect"):
                    detections = self._detect(image, detect)

                if track and self._config.tracking.enabled:
                    with timer.stage("track"):
                        detections = self._tracker.update(detections)

                with timer.stage("segment"):
                    masks = self._segment(image, detections)

                with timer.stage("depth"):
                    depth_map, depth_reused = self._depth(image, camera)

            detections, masks = _drop_empty(detections, masks)

            scene = self._engine.measure_scene(
                detections,
                masks,
                depth_map,
                camera,
                image=image,
                frame_index=frame.index,
                timestamp=frame.timestamp,
                scale_correction=self._scale_correction,
                timer=timer,
            )

            if depth_reused:
                scene.warnings.append(
                    f"depth reused from {self._depth_age} frame(s) ago; a fast-moving object "
                    "may be measured against a slightly stale surface"
                )

            if track and self._config.tracking.enabled:
                scene = self._smoother.update(scene)

            if resize_scale != 1.0:
                _rescale_to_original(scene, resize_scale, frame.size)

            self._frames_processed += 1
            self._latency.add((time.perf_counter() - started) * 1000.0)
            return FrameArtifacts(scene, masks, depth_map, image, camera)

        finally:
            unbind_context("frame", "source")

    # -- video / stream ----------------------------------------------------
    def process_video(
        self,
        source: str | Path | int | FrameSource,
        *,
        callback: Callable[[SceneMeasurement, Frame], None] | None = None,
        max_frames: int | None = None,
        reset: bool = True,
        **source_kwargs: Any,
    ) -> Iterator[tuple[SceneMeasurement, Frame]]:
        """Measure every frame of a video or stream, yielding as it goes.

        Yielding rather than returning a list keeps memory flat on long videos
        and lets a caller start writing output immediately.
        """
        if reset:
            self.reset_state()

        owns_source = not isinstance(source, FrameSource)
        frames = source if isinstance(source, FrameSource) else open_source(source, **source_kwargs)
        every = self._config.runtime.detect_every_n_frames

        try:
            for count, frame in enumerate(frames):
                if max_frames is not None and count >= max_frames:
                    break
                should_detect = (count % every == 0) or self._tracker.active_tracks == 0
                try:
                    scene = self.measure_frame(frame, track=True, detect=should_detect)
                except MeasureCVError as exc:
                    # One bad frame (a decode glitch, a black frame) must not
                    # end a long job.
                    log.warning("frame_failed", index=frame.index, error=str(exc))
                    continue

                if callback is not None:
                    callback(scene, frame)
                yield scene, frame
        finally:
            if owns_source:
                frames.close()

    def process_stream(
        self,
        source: str | int,
        *,
        callback: Callable[[SceneMeasurement, Frame], None] | None = None,
        **source_kwargs: Any,
    ) -> Iterator[tuple[SceneMeasurement, Frame]]:
        """Measure a live camera or network stream until interrupted."""
        yield from self.process_video(source, callback=callback, **source_kwargs)

    # -- internals ---------------------------------------------------------
    def _prepare(
        self,
        image: NDArray[np.uint8],
        override: CameraIntrinsics | None,
        exif: dict[str, Any],
    ) -> tuple[NDArray[np.uint8], CameraIntrinsics, float]:
        """Resize, resolve intrinsics, and optionally rectify distortion."""
        height, width = image.shape[:2]

        # Resolve at the *native* resolution so EXIF-derived focal lengths and
        # stored profiles are interpreted against the size they describe.
        camera = self._resolver.resolve(width, height, exif=exif, override=override)

        max_side = self._config.runtime.max_image_side
        scale = 1.0
        if max(width, height) > max_side:
            scale = max_side / max(width, height)
            new_w, new_h = round(width * scale), round(height * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
            camera = camera.scaled(new_w, new_h)
            log.debug("frame_downscaled", to=f"{new_w}x{new_h}", scale=round(scale, 4))

        if self._config.calibration.undistort and camera.has_distortion:
            image, camera = undistort_image(image, camera)

        return image, camera, scale

    def _detect(self, image: NDArray[np.uint8], run_detection: bool) -> list[Detection]:
        if not run_detection:
            predicted = self._tracker.predicted_detections()
            if predicted:
                return predicted
            # No live tracks to coast on -- fall through to a real detection
            # rather than returning an empty frame.
        detections = self._models.detector.detect(image)
        self._last_detections = detections
        return detections

    def _depth(self, image: NDArray[np.uint8], camera: CameraIntrinsics) -> tuple[Any, bool]:
        """Estimate depth, reusing the cached map when configured to.

        The cache is invalidated on a resolution change, since a depth map for
        a different frame size cannot be indexed by this frame's masks.

        Returns:
            ``(depth_map, was_reused)``.
        """
        every = self._config.runtime.depth_every_n_frames
        shape = (image.shape[0], image.shape[1])

        reusable = (
            every > 1
            and self._cached_depth is not None
            and self._cached_depth_shape == shape
            and self._depth_age < every - 1
        )
        if reusable:
            self._depth_age += 1
            return self._cached_depth, True

        depth_map = self._models.depth_estimator.estimate(image, camera)
        self._cached_depth = depth_map
        self._cached_depth_shape = shape
        self._depth_age = 0
        return depth_map, False

    def _segment(
        self, image: NDArray[np.uint8], detections: Sequence[Detection]
    ) -> list[InstanceMask]:
        if not detections:
            return []
        return self._models.segmenter.segment(image, [d.bbox for d in detections])


def _drop_empty(
    detections: Sequence[Detection], masks: Sequence[InstanceMask]
) -> tuple[list[Detection], list[InstanceMask]]:
    """Remove objects whose mask came back empty, preserving alignment."""
    kept_detections: list[Detection] = []
    kept_masks: list[InstanceMask] = []
    for detection, mask in zip(detections, masks, strict=True):
        if mask.mask.any():
            kept_detections.append(detection)
            kept_masks.append(mask)
    return kept_detections, kept_masks


def _rescale_to_original(
    scene: SceneMeasurement, scale: float, original_size: tuple[int, int]
) -> None:
    """Map pixel-space results back to the caller's coordinate frame.

    Only *pixel* quantities are affected. Metric quantities are already correct
    because the intrinsics were scaled alongside the image -- a smaller image
    with a proportionally smaller focal length describes exactly the same
    physical geometry. Rescaling metres here would be a double correction.
    """
    inverse = 1.0 / scale
    for obj in scene.objects:
        box = obj.detection.bbox
        obj.detection.bbox = type(box)(
            box.x1 * inverse, box.y1 * inverse, box.x2 * inverse, box.y2 * inverse
        )
        obj.mask_area_px = round(obj.mask_area_px * inverse * inverse)
    scene.image_size = original_size
