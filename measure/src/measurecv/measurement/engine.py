"""The measurement engine: masks + depth + calibration -> physical quantities.

This is the stage where per-object failures must not become per-frame
failures. A crowd scene where one object is too small to measure should still
return measurements for the other nine, with a clear reason attached to the
tenth. Every per-object step is therefore individually guarded, and the
failure is recorded on that object rather than raised.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.calibration.scale import ScaleCorrection
from measurecv.core.config import MeasurementConfig
from measurecv.core.exceptions import (
    DegenerateGeometryError,
    InsufficientDataError,
    MeasureCVError,
)
from measurecv.core.logging import get_logger
from measurecv.core.timing import StageTimer
from measurecv.core.types import (
    DepthMap,
    Detection,
    InstanceMask,
    Measured,
    ObjectMeasurement,
    Plane,
    PointCloud,
    SceneMeasurement,
    Unit,
)
from measurecv.geometry.backproject import backproject_depth_map, backproject_mask
from measurecv.geometry.plane import estimate_support_plane
from measurecv.geometry.uncertainty import ErrorBudget
from measurecv.measurement.estimators import (
    MeasurementContext,
    compute_confidence,
    estimate_dimensions,
    estimate_distances,
    estimate_surface_area,
    estimate_volume,
    pairwise_distance,
)

log = get_logger(__name__)

__all__ = ["MeasurementEngine", "SceneAnalytics", "scene_analytics"]


class MeasurementEngine:
    """Stateless-per-frame geometric measurement.

    The engine holds no frame state, which makes it safe to share across
    threads and trivial to test: every call is a pure function of its inputs
    plus the configuration.
    """

    def __init__(self, config: MeasurementConfig, plane_every_n_frames: int = 1) -> None:
        self._config = config
        # A support plane is static for a fixed camera, so re-running RANSAC
        # over 60k points every frame is wasted work. The cache is keyed on
        # nothing but age deliberately: a moving camera invalidates it on the
        # configured schedule rather than never.
        self._plane_every = max(1, plane_every_n_frames)
        self._cached_plane: Plane | None = None
        self._plane_age = 0

    @property
    def config(self) -> MeasurementConfig:
        return self._config

    def reset_plane_cache(self) -> None:
        self._cached_plane = None
        self._plane_age = 0

    def measure_scene(
        self,
        detections: Sequence[Detection],
        masks: Sequence[InstanceMask],
        depth_map: DepthMap,
        intrinsics: CameraIntrinsics,
        *,
        image: np.ndarray | None = None,
        frame_index: int = 0,
        timestamp: float = 0.0,
        scale_correction: ScaleCorrection | None = None,
        timer: StageTimer | None = None,
        seed: int = 0xA11CE,
    ) -> SceneMeasurement:
        """Measure every detected object in one frame.

        Args:
            detections: RT-DETR detections.
            masks: SAM 2 masks, index-aligned with ``detections``.
            depth_map: Metric depth for this frame.
            intrinsics: Camera model matching the frame size.
            image: Optional RGB for point-cloud colouring.
            scale_correction: Optional reference-object scale refinement.

        Returns:
            A :class:`SceneMeasurement`. Objects that could not be measured are
            still present, carrying warnings and a zero confidence.
        """
        if len(detections) != len(masks):
            raise ValueError(
                f"detections ({len(detections)}) and masks ({len(masks)}) must be aligned"
            )

        timer = timer or StageTimer()
        cfg = self._config
        height, width = depth_map.shape
        rng = np.random.default_rng(seed)
        warnings: list[str] = []

        budget = ErrorBudget(
            depth_scale_sigma=depth_map.scale_uncertainty,
            # Per-pixel relative noise is empirically ~40% of the absolute
            # scale error for the Metric3D family: the network is far more
            # self-consistent within a frame than it is calibrated across
            # cameras. Treating the two as equal would double-count the bias.
            depth_noise_sigma=max(0.005, depth_map.scale_uncertainty * 0.4),
            focal_sigma=intrinsics.focal_uncertainty,
            pixel_sigma=1.5,
        )
        if scale_correction is not None:
            # A verified reference object supersedes the model's own scale
            # uncertainty -- that is the entire point of measuring one.
            budget = ErrorBudget(
                depth_scale_sigma=scale_correction.sigma / max(scale_correction.factor, 1e-6),
                depth_noise_sigma=budget.depth_noise_sigma,
                focal_sigma=budget.focal_sigma,
                pixel_sigma=budget.pixel_sigma,
            )

        plane: Plane | None = None
        if cfg.estimate_ground_plane:
            with timer.stage("ground_plane"):
                if (
                    self._plane_every > 1
                    and self._cached_plane is not None
                    and self._plane_age < self._plane_every - 1
                ):
                    plane = self._cached_plane
                    self._plane_age += 1
                else:
                    plane = self._estimate_plane(depth_map, intrinsics)
                    self._cached_plane = plane
                    self._plane_age = 0
            if plane is None:
                warnings.append(
                    "no support plane found; falling back to free 3-D box fitting, "
                    "which is less accurate for objects resting on a surface"
                )

        ctx = MeasurementContext(
            intrinsics=intrinsics,
            depth_map=depth_map,
            config=cfg,
            budget=budget,
            plane=plane,
            rng=rng,
        )

        depth_stats = depth_map.stats()
        coverage = depth_stats.get("coverage", 0.0)

        results: list[ObjectMeasurement] = []

        with timer.stage("measure_objects"):
            for detection, mask in zip(detections, masks, strict=True):
                # The point cloud is deliberately dropped here: it is megabytes
                # per object and nothing downstream of the measurement needs
                # it. Callers who do (export, debugging) rebuild it from the
                # depth map via MeasurementPipeline.measure_frame_full.
                obj, _cloud = self._measure_object(
                    detection,
                    mask,
                    ctx,
                    image=image,
                    depth_coverage=coverage,
                    frame_size=(width, height),
                    scale_correction=scale_correction,
                )
                results.append(obj)

        if cfg.min_confidence > 0:
            kept = [o for o in results if o.confidence >= cfg.min_confidence]
            dropped = len(results) - len(kept)
            if dropped:
                log.debug("low_confidence_objects_dropped", count=dropped)
            results = kept

        scene = SceneMeasurement(
            objects=results,
            frame_index=frame_index,
            timestamp=timestamp,
            image_size=(width, height),
            ground_plane=plane,
            depth_stats=depth_stats,
            timings_ms=timer.finalise(),
            calibration_source=intrinsics.source.value,
            warnings=warnings,
        )
        return scene

    # -- internals ---------------------------------------------------------
    def _estimate_plane(self, depth_map: DepthMap, intrinsics: CameraIntrinsics) -> Plane | None:
        """Fit the dominant support surface from a strided scene cloud.

        A stride is used rather than the full frame: plane fitting needs
        coverage, not resolution, and striding turns a two-megapixel fit into a
        cheap one with no measurable loss of accuracy.
        """
        cfg = self._config
        h, w = depth_map.shape
        stride = max(1, int(math.sqrt((h * w) / 60000)))

        scene_cloud = backproject_depth_map(depth_map, intrinsics, stride=stride, max_points=60000)
        if len(scene_cloud) < 200:
            return None

        return estimate_support_plane(
            scene_cloud,
            distance_threshold=cfg.ground_distance_threshold_m,
            max_iterations=cfg.ground_ransac_iterations,
            min_inlier_ratio=cfg.ground_min_inlier_ratio,
            gravity_prior_deg=cfg.gravity_prior_deg,
        )

    def _measure_object(
        self,
        detection: Detection,
        mask: InstanceMask,
        ctx: MeasurementContext,
        *,
        image: np.ndarray | None,
        depth_coverage: float,
        frame_size: tuple[int, int],
        scale_correction: ScaleCorrection | None,
    ) -> tuple[ObjectMeasurement, PointCloud | None]:
        """Measure one object, converting any failure into a warning."""
        cfg = self._config
        width, height = frame_size
        obj = ObjectMeasurement(detection=detection, mask_area_px=mask.area_px)

        truncated = detection.bbox.touches_border(width, height)
        if truncated and cfg.reject_truncated:
            obj.warnings.append("object touches the frame border; measurements are lower bounds")

        try:
            cloud, report = backproject_mask(
                mask, ctx.depth_map, ctx.intrinsics, cfg, image=image, rng=ctx.rng
            )
        except InsufficientDataError as exc:
            obj.warnings.append(f"not measurable: {exc.message}")
            obj.confidence = 0.0
            return obj, None
        except (ValueError, MeasureCVError) as exc:
            log.warning("backprojection_failed", label=detection.label, error=str(exc))
            obj.warnings.append(f"back-projection failed: {exc}")
            obj.confidence = 0.0
            return obj, None

        obj.point_count = len(cloud)

        try:
            dims, box, _method = estimate_dimensions(cloud, ctx, report)
        except DegenerateGeometryError as exc:
            obj.warnings.append(f"shape fit failed: {exc.message}")
            obj.confidence = 0.0
            return obj, cloud

        obj.dimensions = dims

        try:
            obj.surface_area = estimate_surface_area(cloud, ctx, report)
        except Exception as exc:  # area is optional; never fail the object for it
            log.debug("surface_area_failed", error=str(exc))
            obj.warnings.append("surface area unavailable")

        try:
            volume, alternatives = estimate_volume(cloud, ctx, box, dims)
            obj.volume = volume
            obj.extras["volume_models_m3"] = alternatives
        except Exception as exc:
            log.debug("volume_failed", error=str(exc))
            obj.warnings.append("volume unavailable")

        obj.footprint_area = Measured(
            box.footprint_area,
            box.footprint_area * 2.0 * ctx.budget.depth_scale_sigma,
            Unit.SQUARE_METRE,
            dims.length.method,
        )

        distance, nearest, centroid = estimate_distances(cloud, ctx)
        obj.distance = distance
        obj.nearest_distance = nearest
        obj.position = centroid

        if ctx.plane is not None:
            from measurecv.geometry.plane import SupportFrame

            frame = SupportFrame.from_plane(ctx.plane)
            obj.world_position = frame.to_world(centroid[None, :])[0]
            clearance = float(ctx.plane.signed_distance(cloud.points).min())
            obj.extras["ground_clearance_m"] = round(clearance, 4)

        # Apply a reference-object scale correction to every derived quantity,
        # with the correct power of the scale factor for each.
        if scale_correction is not None:
            obj = _apply_scale_correction(obj, scale_correction)

        obj.extras["filter_report"] = report.to_dict()
        obj.extras["box_condition"] = round(box.condition, 4)

        confidence, warnings = compute_confidence(
            detection_score=detection.score,
            mask_iou=mask.iou_score,
            mask_stability=mask.stability,
            report=report,
            box=box,
            n_points=len(cloud),
            min_points=cfg.min_points,
            truncated=truncated,
            focal_uncertainty=ctx.intrinsics.focal_uncertainty,
            depth_coverage=depth_coverage,
        )
        obj.confidence = confidence
        obj.warnings.extend(warnings)

        return obj, cloud


def _apply_scale_correction(
    obj: ObjectMeasurement, correction: ScaleCorrection
) -> ObjectMeasurement:
    """Rescale all quantities by the appropriate power of the scale factor."""
    if obj.dimensions is not None:
        obj.dimensions.length = correction.apply_length(obj.dimensions.length)
        obj.dimensions.width = correction.apply_length(obj.dimensions.width)
        obj.dimensions.height = correction.apply_length(obj.dimensions.height)
    if obj.surface_area is not None:
        obj.surface_area = correction.apply_area(obj.surface_area)
    if obj.footprint_area is not None:
        obj.footprint_area = correction.apply_area(obj.footprint_area)
    if obj.volume is not None:
        obj.volume = correction.apply_volume(obj.volume)
    if obj.distance is not None:
        obj.distance = correction.apply_length(obj.distance)
    if obj.nearest_distance is not None:
        obj.nearest_distance = correction.apply_length(obj.nearest_distance)
    if obj.position is not None:
        obj.position = obj.position * correction.factor
    if obj.world_position is not None:
        obj.world_position = obj.world_position * correction.factor
    return obj


# ---------------------------------------------------------------------------
# Scene-level analytics
# ---------------------------------------------------------------------------
class SceneAnalytics:
    """Derived relationships between measured objects."""

    def __init__(self, scene: SceneMeasurement) -> None:
        self.scene = scene

    def pairwise_distances(self, budget: ErrorBudget | None = None) -> list[dict[str, Any]]:
        """Centre-to-centre distance for every measurable pair."""
        budget = budget or ErrorBudget()
        # Bind the position alongside the object so the non-None guarantee
        # survives into the loop body, for the reader as much as the checker.
        measurable = [
            (i, o, o.position) for i, o in enumerate(self.scene.objects) if o.position is not None
        ]
        out: list[dict[str, Any]] = []
        for ai in range(len(measurable)):
            for bi in range(ai + 1, len(measurable)):
                i, a, a_position = measurable[ai]
                j, b, b_position = measurable[bi]
                d = pairwise_distance(
                    PointCloud(a_position[None, :]), PointCloud(b_position[None, :]), budget
                )
                out.append(
                    {
                        "a": {"index": i, "label": a.detection.label, "track_id": a.track_id},
                        "b": {"index": j, "label": b.detection.label, "track_id": b.track_id},
                        "distance": d.to_dict(),
                    }
                )
        return out

    def summary(self) -> dict[str, Any]:
        """Aggregate statistics over the frame."""
        objects = self.scene.objects
        measured = [o for o in objects if o.dimensions is not None]
        volumes = [o.volume.value for o in measured if o.volume is not None]
        confidences = [o.confidence for o in objects]
        by_label: dict[str, int] = {}
        for o in objects:
            by_label[o.detection.label] = by_label.get(o.detection.label, 0) + 1
        return {
            "objects_detected": len(objects),
            "objects_measured": len(measured),
            "counts_by_label": by_label,
            "total_volume_m3": round(sum(volumes), 6) if volumes else 0.0,
            "mean_confidence": round(float(np.mean(confidences)), 4) if confidences else 0.0,
            "min_confidence": round(float(np.min(confidences)), 4) if confidences else 0.0,
        }


def scene_analytics(scene: SceneMeasurement) -> SceneAnalytics:
    """Convenience constructor."""
    return SceneAnalytics(scene)
