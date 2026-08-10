"""Typed, layered configuration.

Precedence (highest wins):

1. Explicit keyword overrides passed to :func:`load_config`.
2. Environment variables, ``MEASURECV__SECTION__FIELD`` (double underscore
   separates nesting levels).
3. A YAML file (``--config`` / ``MEASURECV_CONFIG``).
4. The defaults declared here.

Pydantic gives us validation *and* a self-documenting schema; the cross-field
validators below catch the configuration mistakes that would otherwise surface
as silently wrong measurements (e.g. asking for a ground-plane frame while
disabling plane estimation).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from measurecv.core.exceptions import ConfigurationError

__all__ = [
    "ApiConfig",
    "AppConfig",
    "CalibrationConfig",
    "DepthConfig",
    "DetectionConfig",
    "MeasurementConfig",
    "RuntimeConfig",
    "SegmentationConfig",
    "TrackingConfig",
    "load_config",
]


class _Section(BaseModel):
    """Base for every config section.

    ``extra="forbid"`` is the important part, and it must be set on the nested
    models rather than only on the root: without it a typo like
    ``mask_erosion_px`` (for ``mask_erode_px``) is silently discarded, the
    default stays in force, and the operator is left wondering why their
    setting had no effect. Failing loudly at startup is far cheaper than
    debugging a measurement that was quietly using the wrong parameters.

    ``protected_namespaces=()`` allows the ``model_id`` / ``model_name`` fields,
    which Pydantic would otherwise reject for colliding with its own ``model_``
    prefix.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class DetectionConfig(_Section):
    """RT-DETR settings."""

    backend: Literal["transformers", "onnx", "synthetic"] = "transformers"
    model_id: str = "PekingU/rtdetr_v2_r50vd"
    """RT-DETRv2 R50 is the accuracy/latency sweet spot. Use
    ``rtdetr_v2_r18vd`` for edge deployments, ``r101vd`` for max accuracy."""
    onnx_path: Path | None = None
    score_threshold: float = Field(0.45, ge=0.0, le=1.0)
    max_detections: int = Field(100, ge=1, le=900)
    class_whitelist: list[str] | None = None
    """Restrict to these COCO class names; ``None`` keeps everything."""
    min_box_area_px: float = Field(64.0, ge=0.0)
    """Reject specks -- they never yield enough 3-D points to measure."""
    compile_model: bool = False


class SegmentationConfig(_Section):
    """SAM 2 settings."""

    backend: Literal["transformers", "synthetic"] = "transformers"
    model_id: str = "facebook/sam2.1-hiera-large"
    video_model_id: str | None = None
    """Defaults to ``model_id`` -- SAM 2.1 checkpoints serve both paths."""
    multimask_output: bool = True
    """Ask SAM for 3 hypotheses and keep the best by predicted IoU. Costs
    almost nothing (the mask decoder is tiny) and materially improves masks on
    ambiguous box prompts."""
    mask_logit_threshold: float = 0.0
    box_prompt_padding: float = Field(0.0, ge=0.0, le=0.25)
    use_point_prompt: bool = True
    """Add the box-centre as a positive point prompt alongside the box; helps
    SAM lock onto the intended object inside a crowded box."""
    min_mask_area_px: int = Field(100, ge=1)
    fill_holes_px: int = Field(256, ge=0)
    """Fill enclosed holes up to this area. Pinholes in a mask remove valid
    interior depth samples and corrupt the boundary-shrink estimate; genuine
    large gaps (a chair back) are left alone."""
    remove_specks_px: int = Field(64, ge=0)
    """Drop disconnected fragments below this area -- they sit at the wrong
    depth and stretch the point cloud."""
    encoder_cache_size: int = Field(4, ge=1, le=64)
    """The image encoder dominates SAM 2 cost and is prompt-independent, so its
    output is cached and reused across all objects in a frame."""


class DepthConfig(_Section):
    """Metric3D settings."""

    backend: Literal["torch_hub", "onnx", "synthetic"] = "torch_hub"
    hub_repo: str = "yvanyin/metric3d"
    model_name: str = "metric3d_vit_large"
    """``metric3d_vit_small`` (fast) | ``vit_large`` (balanced) |
    ``vit_giant2`` (best)."""
    onnx_path: Path | None = None
    input_size: tuple[int, int] = (616, 1064)
    """Canonical network input (H, W) for the ViT variants.

    **Do not shrink this to go faster.** It is the obvious lever -- halving it
    is ~2x quicker and the canonical transform appears to account for the
    resize -- but Metric3D's learned priors are resolution-dependent, so the
    network's *canonical* output changes too. Measured on a real scene:

    ====================  ========  ==============
    input_size            latency   depth error
    ====================  ========  ==============
    616 x 1064 (trained)   7520 ms   baseline
    462 x 798              3700 ms   +17.6%
    392 x 672              2440 ms   +23.6%
    308 x 532              1490 ms   +31.7%
    224 x 392               750 ms   +44.8%
    ====================  ========  ==============

    Nothing errors and the depth map still looks perfectly reasonable -- it is
    simply wrong. To go faster, lower ``runtime.depth_every_n_frames`` or use a
    GPU; both keep the network at its trained resolution."""
    canonical_focal: float = 1000.0
    """Metric3D is trained in a canonical camera space with this focal length.
    Recovering true metric scale *requires* rescaling by ``f_real / 1000`` --
    skipping this step is the single most common source of a systematically
    wrong measurement."""
    max_depth_m: float = Field(200.0, gt=0)
    min_depth_m: float = Field(0.05, gt=0)
    scale_uncertainty: float = Field(0.05, ge=0.0, le=1.0)
    """Relative 1-sigma of the metric scale. ~5% reflects Metric3D v2's
    reported zero-shot absolute-relative error on unseen cameras."""
    use_confidence: bool = True
    compile_model: bool = False


class CalibrationConfig(_Section):
    """Camera model and how to obtain it."""

    profile: Path | None = None
    """Path to a saved intrinsics JSON produced by ``measurecv calibrate``."""
    allow_exif: bool = True
    """Derive focal length from EXIF when no profile is supplied."""
    default_hfov_deg: float = Field(60.0, gt=1.0, lt=179.0)
    """Last-resort assumption. Roughly a 28 mm-equivalent phone camera."""
    undistort: bool = True
    board_type: Literal["chessboard", "charuco"] = "chessboard"
    board_shape: tuple[int, int] = (9, 6)
    """Inner-corner counts (cols, rows)."""
    square_size_m: float = Field(0.025, gt=0)
    marker_size_m: float = Field(0.018, gt=0)
    charuco_dict: str = "DICT_4X4_50"
    min_calibration_views: int = Field(8, ge=3)
    max_rms_error_px: float = Field(1.0, gt=0)
    """Reject a calibration whose reprojection RMS exceeds this."""


class MeasurementConfig(_Section):
    """The accuracy-critical knobs of the geometry engine."""

    mask_erode_px: int = Field(3, ge=0, le=25)
    """Erode masks before back-projection. Boundary pixels mix foreground and
    background depth (the depth model bleeds across edges), and those mixed
    samples are exactly the ones that sit at the extremes of the point cloud --
    so they corrupt extent estimates far more than their count suggests."""
    depth_edge_suppression: bool = True
    """Additionally drop pixels near strong depth discontinuities."""
    depth_edge_threshold: float = Field(0.06, gt=0)
    """Relative depth gradient treated as an edge."""
    outlier_mad_scale: float = Field(3.0, gt=0)
    """Robust (median absolute deviation) depth gate within each mask."""
    statistical_outlier_k: int = Field(16, ge=0)
    """k for the 3-D statistical outlier filter; 0 disables it."""
    statistical_outlier_std: float = Field(2.0, gt=0)
    min_points: int = Field(120, ge=8)
    """Below this, refuse to measure rather than emit a noisy guess."""
    max_points: int = Field(20000, ge=100)
    """Subsample cap -- bounds hull/PCA cost per object."""

    estimate_ground_plane: bool = True
    ground_ransac_iterations: int = Field(600, ge=50)
    ground_distance_threshold_m: float = Field(0.02, gt=0)
    ground_min_inlier_ratio: float = Field(0.12, gt=0, le=1.0)
    gravity_prior_deg: float = Field(35.0, ge=0, le=90)
    """Reject candidate support planes whose normal deviates from the assumed
    up-axis by more than this -- stops RANSAC latching onto a wall."""

    dimension_method: Literal["auto", "obb", "ground_aligned", "planar"] = "auto"
    volume_method: Literal["auto", "obb", "hull", "extrusion", "ellipsoid"] = "auto"
    obb_percentile: float = Field(1.0, ge=0.0, le=10.0)
    """Trim this percentile from each end of every axis when measuring extent.
    A pure min/max is maximally sensitive to the single worst outlier."""
    surface_area_correction: bool = True
    """Divide each pixel's area by cos(theta) between surface normal and view
    ray, recovering true area on slanted surfaces."""

    monte_carlo_samples: int = Field(0, ge=0, le=4096)
    """0 = analytic first-order propagation (fast, the default). Setting a few
    hundred switches to Monte Carlo, which handles the nonlinearity of hull and
    OBB fits more faithfully at a real cost."""
    reject_truncated: bool = True
    """Flag (don't silently measure) objects clipped by the frame border."""
    min_confidence: float = Field(0.0, ge=0.0, le=1.0)
    """Drop measurements below this composite confidence."""


class TrackingConfig(_Section):
    """Multi-object tracking for video/live modes."""

    enabled: bool = True
    max_age: int = Field(30, ge=1)
    min_hits: int = Field(3, ge=1)
    iou_threshold: float = Field(0.3, ge=0.0, le=1.0)
    high_threshold: float = Field(0.6, ge=0.0, le=1.0)
    """Score at which a detection counts as confident. Only confident
    detections spawn new tracks; the rest are still used to *sustain* existing
    ones, which is what carries identity through an occlusion. Set this above
    your detector's typical score and no track will ever start."""
    smoothing: Literal["none", "ema", "median"] = "ema"
    smoothing_alpha: float = Field(0.35, gt=0.0, le=1.0)
    """EMA weight on the *new* measurement. Lower = steadier readout."""
    smoothing_window: int = Field(9, ge=1)


class RuntimeConfig(_Section):
    """Execution and scheduling."""

    device: Literal["auto", "cuda", "mps", "cpu"] | str = "auto"
    precision: Literal["auto", "fp32", "fp16", "bf16"] = "auto"
    deterministic: bool = False
    torch_threads: int | None = None
    warmup: bool = True
    """Run one synthetic frame at startup so the first real request doesn't pay
    cuDNN autotuning and lazy-init costs."""
    max_image_side: int = Field(1600, ge=256, le=8192)
    """Downscale huge uploads before inference; intrinsics are scaled to match
    so measurements are unaffected."""
    detect_every_n_frames: int = Field(1, ge=1)
    """Run RT-DETR every n frames; the motion model covers the gaps."""
    depth_every_n_frames: int = Field(1, ge=1)
    """Run Metric3D every n frames and reuse the last map in between.

    The dominant cost by a wide margin (~65% of a CPU frame), and the quantity
    that changes most slowly -- a scene's geometry is near-static between
    consecutive frames even when objects move within it. Unlike shrinking
    ``depth.input_size``, this keeps the network at its trained resolution, so
    the depth that *is* computed stays correct; the only cost is that a moving
    object may be measured against a slightly stale surface.

    Stale frames are flagged in the scene warnings so a reading taken during a
    fast movement is attributable."""
    ground_plane_every_n_frames: int = Field(1, ge=1)
    """Re-fit the support plane every n frames, reusing it in between.

    For a fixed camera the floor genuinely does not move, so re-running RANSAC
    on 60k points every frame is wasted work."""
    queue_size: int = Field(8, ge=1)
    drop_frames_when_busy: bool = True
    """Live streams must stay real-time; buffering adds latency without value."""
    model_ttl_seconds: float = Field(0.0, ge=0.0)
    """Unload idle models after this many seconds (0 = keep resident)."""


class ApiConfig(_Section):
    """HTTP surface."""

    host: str = "0.0.0.0"
    port: int = Field(8000, ge=1, le=65535)
    workers: int = Field(1, ge=1)
    """Keep at 1 with a GPU: multiple processes would each hold a model copy."""
    root_path: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    max_upload_mb: float = Field(50.0, gt=0)
    request_timeout_s: float = Field(120.0, gt=0)
    enable_metrics: bool = True
    enable_docs: bool = True
    api_keys: list[str] = Field(default_factory=list)
    """When non-empty, requests must carry a matching ``X-API-Key``."""
    max_concurrent_inferences: int = Field(2, ge=1)


class AppConfig(BaseSettings):
    """Root configuration object."""

    model_config = SettingsConfigDict(
        env_prefix="MEASURECV__",
        env_nested_delimiter="__",
        extra="forbid",
        validate_assignment=True,
        protected_namespaces=(),
    )

    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    depth: DepthConfig = Field(default_factory=DepthConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    measurement: MeasurementConfig = Field(default_factory=MeasurementConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)

    log_level: str = "INFO"
    log_json: bool = False
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "measurecv")
    output_dir: Path = Path("outputs")

    @field_validator("log_level")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return v.upper()

    @model_validator(mode="after")
    def _cross_checks(self) -> AppConfig:
        m = self.measurement
        if m.dimension_method == "ground_aligned" and not m.estimate_ground_plane:
            raise ValueError(
                "measurement.dimension_method='ground_aligned' requires "
                "measurement.estimate_ground_plane=true"
            )
        if m.volume_method == "extrusion" and not m.estimate_ground_plane:
            raise ValueError(
                "measurement.volume_method='extrusion' requires a support plane; "
                "enable measurement.estimate_ground_plane"
            )
        if m.max_points < m.min_points:
            raise ValueError("measurement.max_points must be >= min_points")
        if self.detection.backend == "onnx" and self.detection.onnx_path is None:
            raise ValueError("detection.onnx_path is required when detection.backend='onnx'")
        if self.depth.backend == "onnx" and self.depth.onnx_path is None:
            raise ValueError("depth.onnx_path is required when depth.backend='onnx'")
        if self.depth.min_depth_m >= self.depth.max_depth_m:
            raise ValueError("depth.min_depth_m must be < depth.max_depth_m")
        if self.api.workers > 1 and str(self.runtime.device).startswith("cuda"):
            raise ValueError(
                "api.workers>1 with a CUDA device would load one model set per worker; "
                "scale with replicas behind a load balancer instead"
            )
        return self

    def synthetic(self) -> AppConfig:
        """Return a copy with all neural backends swapped for deterministic
        stand-ins. Used by the test-suite and by ``--dry-run`` so the full
        pipeline can be exercised without weights, network, or a GPU.
        """
        data = self.model_dump()
        data["detection"]["backend"] = "synthetic"
        data["segmentation"]["backend"] = "synthetic"
        data["depth"]["backend"] = "synthetic"
        data["runtime"]["warmup"] = False
        return AppConfig(**data)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None, **overrides: Any) -> AppConfig:
    """Build an :class:`AppConfig` from YAML + environment + explicit overrides."""
    path = path or os.environ.get("MEASURECV_CONFIG")

    data: dict[str, Any] = {}
    if path:
        cfg_path = Path(path)
        if not cfg_path.is_file():
            raise ConfigurationError(f"config file not found: {cfg_path}", path=str(cfg_path))
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"invalid YAML in {cfg_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"config root must be a mapping: {cfg_path}")
        data = loaded

    if overrides:
        data = _deep_merge(data, overrides)

    try:
        return AppConfig(**data)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigurationError(f"invalid configuration: {exc}") from exc
