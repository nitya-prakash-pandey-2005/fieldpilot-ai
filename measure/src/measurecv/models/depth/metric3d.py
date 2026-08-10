"""Metric3D metric depth backend.

The canonical camera transform
------------------------------
This is the part that everything else depends on, and the part most
implementations get wrong.

Metric3D is not trained to predict depth for *your* camera. It is trained in a
**canonical camera space** with a fixed focal length (1000 px). During
training, every sample is resized so that its effective focal length becomes
1000, and the ground-truth depth is rescaled by the same factor. The network
therefore learns a single, consistent depth-vs-appearance mapping instead of
having to internally infer each camera's focal length -- which is what makes
zero-shot *metric* (rather than relative) depth possible at all.

The consequence at inference time is that raw network output is in canonical
units and must be transformed back::

    scale       = min(H_in / H, W_in / W)     # resize into the network window
    f_canonical = f_real * scale              # focal after that resize
    depth_real  = depth_pred * f_canonical / 1000.0

Skip the final line and you get depth that looks entirely plausible -- smooth,
correctly ordered, right-shaped -- and is wrong by the ratio of your focal
length to 1000. On a 1600 px-wide phone photo that is a factor of about 1.4,
i.e. a 40% error on every dimension the system reports, with nothing in the
output to indicate a problem. It is the single highest-leverage line of code
in this repository, which is why it is isolated in
:func:`_canonical_to_metric` and covered by a dedicated test.

The dependence on focal length also explains why calibration error propagates
straight into metric error, and why
:class:`~measurecv.geometry.uncertainty.ErrorBudget` treats the focal
uncertainty as a systematic term that no amount of averaging can remove.
"""

from __future__ import annotations

import contextlib
import sys
import types
from collections.abc import Iterator
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.config import DepthConfig
from measurecv.core.device import DeviceContext, autocast_context
from measurecv.core.exceptions import DepthEstimationError, ModelLoadError
from measurecv.core.logging import get_logger
from measurecv.core.types import DepthMap
from measurecv.models.base import DepthEstimator

log = get_logger(__name__)

__all__ = ["Metric3DDepthEstimator"]

#: ImageNet statistics in 0-255 units, as used by Metric3D's own preprocessing.
_MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
_STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)


def _canonical_to_metric(
    depth_canonical: NDArray[np.float32],
    focal_px: float,
    resize_scale: float,
    canonical_focal: float,
) -> NDArray[np.float32]:
    """Convert canonical-space depth to metres.

    Args:
        depth_canonical: Raw network output.
        focal_px: The *original* image focal length in pixels.
        resize_scale: Factor applied when fitting the image into the network
            input window.
        canonical_focal: The training-time canonical focal length (1000).

    Returns:
        Depth in metres.
    """
    if focal_px <= 0:
        raise DepthEstimationError(f"focal length must be positive, got {focal_px}")
    effective_focal = focal_px * resize_scale
    return depth_canonical * (effective_focal / canonical_focal)


def _install_mmcv_shim() -> bool:
    """Satisfy Metric3D's unused ``mmcv`` import.

    ``mono/utils/comm.py`` does ``from mmcv.utils import collect_env,
    get_git_hash`` at module scope. Both names are **only** used inside
    commented-out code, but the import still runs -- so loading the model
    requires OpenMMLab's ``mmcv``, which needs a compiler and has no wheels for
    recent Python versions. That turns a diagnostic convenience into a hard
    install blocker.

    ``mmengine`` (pure Python) provides the real ``Config`` and ``get_git_hash``
    that the hub script actually wants, so the shim forwards those and stubs
    the one genuinely unused function.

    Returns:
        True if a shim was installed, False if real ``mmcv`` was present.
    """
    if "mmcv" in sys.modules:
        return False
    try:
        import mmcv  # noqa: F401

        return False
    except ImportError:
        pass

    try:
        from mmengine import Config, DictAction
        from mmengine.utils import get_git_hash
    except ImportError as exc:
        raise ModelLoadError(
            "Metric3D needs 'mmengine' (pure Python): pip install mmengine. "
            "It is not declared by the hub script but is imported by it.",
            missing=str(exc),
        ) from exc

    mmcv_module = types.ModuleType("mmcv")
    utils_module = types.ModuleType("mmcv.utils")
    utils_module.Config = Config  # type: ignore[attr-defined]
    utils_module.DictAction = DictAction  # type: ignore[attr-defined]
    utils_module.get_git_hash = get_git_hash  # type: ignore[attr-defined]
    utils_module.collect_env = lambda: {}  # type: ignore[attr-defined]
    mmcv_module.utils = utils_module  # type: ignore[attr-defined]

    sys.modules["mmcv"] = mmcv_module
    sys.modules["mmcv.utils"] = utils_module
    log.info("mmcv_shim_installed", reason="metric3d imports mmcv.utils but never calls it")
    return True


#: Torch factory functions that Metric3D calls with a hardcoded device.
_TORCH_FACTORIES = ("linspace", "arange", "zeros", "ones", "empty", "full", "tensor", "eye")


@contextlib.contextmanager
def _device_compat(target: str) -> Iterator[None]:
    """Redirect Metric3D's hardcoded ``device="cuda"`` to ``target``.

    Metric3D's decode heads construct their depth-bin and mesh-grid tensors
    with a literal ``device="cuda"`` (see ``RAFTDepthNormalDPTDecoder5``), so
    the published model raises ``Torch not compiled with CUDA enabled`` on any
    CPU-only or Apple-Silicon machine regardless of where the weights were
    placed.

    Rather than vendor a patched copy of the upstream source -- which would
    have to be re-synced on every release -- this rewrites the ``device``
    keyword on torch's factory functions for the duration of the call. The
    patch is scoped to a context manager, restores the originals in a
    ``finally``, and is a no-op when the target really is CUDA, so it cannot
    affect a normal GPU deployment.

    The numerical result is unchanged: these tensors are index and anchor
    grids, and where they are allocated has no bearing on their values.
    """
    import torch

    if "cuda" in target:
        yield
        return

    originals = {name: getattr(torch, name) for name in _TORCH_FACTORIES}

    def redirect(fn: Any) -> Any:
        def patched(*args: Any, **kwargs: Any) -> Any:
            device = kwargs.get("device")
            if device is not None and "cuda" in str(device):
                kwargs["device"] = target
            return fn(*args, **kwargs)

        return patched

    for name, fn in originals.items():
        setattr(torch, name, redirect(fn))
    try:
        yield
    finally:
        for name, fn in originals.items():
            setattr(torch, name, fn)


def preprocess_metric3d(
    image: NDArray[np.uint8], input_size: tuple[int, int]
) -> tuple[NDArray[np.float32], float, tuple[int, int, int, int]]:
    """Resize into the canonical window, pad, and normalise.

    The image is scaled by ``min`` of the two ratios so it fits entirely inside
    the network window while preserving aspect ratio -- an anisotropic resize
    would change the effective fx and fy by different factors and break the
    single-scalar canonical transform that :func:`_canonical_to_metric`
    depends on.

    Padding uses the dataset mean colour rather than black: the network sees
    the padding, and a black border is a strong artificial edge whose depth
    artefacts bleed into the real image region.

    Returns:
        ``(chw_float32, resize_scale, (top, bottom, left, right))``.
    """
    target_h, target_w = input_size
    h, w = image.shape[:2]

    scale = min(target_h / h, target_w / w)
    new_w, new_h = round(w * scale), round(h * scale)
    # INTER_AREA is the correct filter for downscaling (it integrates source
    # pixels); INTER_LINEAR aliases and injects high-frequency detail that a
    # depth network reads as texture.
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (new_w, new_h), interpolation=interp)

    pad_h = target_h - new_h
    pad_w = target_w - new_w
    pad_top = pad_h // 2
    pad_bottom = pad_h - pad_top
    pad_left = pad_w // 2
    pad_right = pad_w - pad_left

    padded = cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=_MEAN.tolist(),
    )

    normalised = (padded.astype(np.float32) - _MEAN) / _STD
    return (
        np.ascontiguousarray(normalised.transpose(2, 0, 1)),
        scale,
        (pad_top, pad_bottom, pad_left, pad_right),
    )


def postprocess_metric3d(
    depth_canonical: NDArray[np.float32],
    pad: tuple[int, int, int, int],
    output_size: tuple[int, int],
    intrinsics: CameraIntrinsics,
    scale: float,
    config: DepthConfig,
) -> NDArray[np.float32]:
    """Un-pad, resize, and apply the canonical -> metric conversion."""
    pad_top, pad_bottom, pad_left, pad_right = pad
    cropped = depth_canonical[
        pad_top : depth_canonical.shape[0] - pad_bottom,
        pad_left : depth_canonical.shape[1] - pad_right,
    ]
    h, w = output_size
    # Bilinear: depth is piecewise smooth, and nearest-neighbour would create
    # blocky steps that the depth-edge filter then mistakes for real geometry.
    resized = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    metric = _canonical_to_metric(resized, intrinsics.fx, scale, config.canonical_focal)
    metric = np.clip(metric, 0.0, config.max_depth_m)
    metric[~np.isfinite(metric) | (metric < config.min_depth_m)] = 0.0
    return metric.astype(np.float32)


class Metric3DDepthEstimator(DepthEstimator):
    """Metric3D v2 via ``torch.hub``."""

    def __init__(self, config: DepthConfig, device: DeviceContext | None = None) -> None:
        super().__init__(device)
        self._config = config
        self._model: Any = None

    @property
    def name(self) -> str:
        return f"metric3d:{self._config.model_name}"

    def _load(self) -> None:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover
            raise ModelLoadError(
                "Metric3D needs the 'models' extra: pip install 'measurecv[models]'",
                missing=str(exc),
            ) from exc

        cfg = self._config
        _install_mmcv_shim()

        try:
            # The device patch must cover construction as well as inference:
            # the decode head allocates its depth-bin anchors during the first
            # forward pass, but some variants do so at build time.
            with _device_compat(self._device.device):
                model = torch.hub.load(cfg.hub_repo, cfg.model_name, pretrain=True, trust_repo=True)
        except Exception as exc:
            raise ModelLoadError(
                f"could not load Metric3D '{cfg.model_name}' from '{cfg.hub_repo}': {exc}. "
                "Check network access and that the model name is valid "
                "(metric3d_vit_small | metric3d_vit_large | metric3d_vit_giant2). "
                "Metric3D also needs 'timm' and 'mmengine' installed.",
                hub_repo=cfg.hub_repo,
                model_name=cfg.model_name,
            ) from exc

        model.eval()
        model.to(self._device.torch_device)
        if self._device.is_cuda and self._device.dtype_name != "fp32":
            model = model.to(self._device.torch_dtype)

        if cfg.compile_model:
            try:
                model = torch.compile(model, dynamic=False)
            except Exception as exc:
                log.warning("torch_compile_failed", model=self.name, error=str(exc))

        self._model = model

    def _unload(self) -> None:
        self._model = None

    # -- preprocessing -----------------------------------------------------
    def _preprocess(self, image: NDArray[np.uint8]) -> tuple[Any, float, tuple[int, int, int, int]]:
        """Metric3D preprocessing, returned as a device tensor."""
        import torch

        array, scale, pad = preprocess_metric3d(image, self._config.input_size)
        tensor = torch.from_numpy(array).unsqueeze(0)
        tensor = tensor.to(self._device.torch_device)
        if self._device.is_cuda and self._device.dtype_name != "fp32":
            tensor = tensor.to(self._device.torch_dtype)

        return tensor, scale, pad

    # -- inference ---------------------------------------------------------
    def estimate(self, image: NDArray[np.uint8], intrinsics: CameraIntrinsics) -> DepthMap:
        self.ensure_loaded()

        import torch

        cfg = self._config
        h, w = image.shape[:2]
        if (intrinsics.width, intrinsics.height) != (w, h):
            raise DepthEstimationError(
                f"intrinsics are for {intrinsics.width}x{intrinsics.height} but the image is "
                f"{w}x{h}; metric scale depends on the focal length matching the actual frame",
                image_size=[w, h],
                intrinsics_size=[intrinsics.width, intrinsics.height],
            )

        tensor, scale, pad = self._preprocess(image)

        with (
            torch.inference_mode(),
            autocast_context(self._device),
            _device_compat(self._device.device),
        ):
            output = self._model.inference({"input": tensor})

        depth_t, confidence_t = _unpack_output(output)

        depth_t = depth_t.squeeze().float()
        pad_top, pad_bottom, pad_left, pad_right = pad
        depth_t = depth_t[
            pad_top : depth_t.shape[0] - pad_bottom,
            pad_left : depth_t.shape[1] - pad_right,
        ]

        # Resize back to the input resolution. Bilinear is right here: depth is
        # piecewise smooth, and nearest would produce blocky steps that the
        # depth-edge filter would then flag as real discontinuities.
        depth_t = torch.nn.functional.interpolate(
            depth_t[None, None], size=(h, w), mode="bilinear", align_corners=False
        ).squeeze()

        depth = depth_t.detach().cpu().numpy().astype(np.float32)

        # ---- the canonical -> metric step ----
        # fx is used (not the fx/fy mean) because the resize is isotropic and
        # Metric3D's canonical space is defined on the horizontal focal length.
        depth = _canonical_to_metric(depth, intrinsics.fx, scale, cfg.canonical_focal)

        depth = np.clip(depth, 0.0, cfg.max_depth_m)
        invalid = ~np.isfinite(depth) | (depth < cfg.min_depth_m)
        depth[invalid] = 0.0

        confidence: NDArray[np.float32] | None = None
        if cfg.use_confidence and confidence_t is not None:
            confidence = _resize_confidence(confidence_t, pad, (h, w))

        valid_fraction = float((~invalid).mean())
        if valid_fraction < 0.2:
            raise DepthEstimationError(
                f"only {valid_fraction:.1%} of the depth map is usable; "
                "the image may be too dark, blurred or out of domain",
                valid_fraction=valid_fraction,
            )

        return DepthMap(
            depth=depth,
            confidence=confidence,
            scale_uncertainty=cfg.scale_uncertainty,
        )

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "model_name": self._config.model_name,
            "hub_repo": self._config.hub_repo,
            "canonical_focal": self._config.canonical_focal,
            "input_size": list(self._config.input_size),
        }


def _unpack_output(output: Any) -> tuple[Any, Any | None]:
    """Normalise Metric3D's return shape across model variants.

    ``inference`` returns ``(pred_depth, confidence, output_dict)`` for the ViT
    models, but some variants return only a tensor or a dict.
    """
    if isinstance(output, tuple | list):
        depth = output[0]
        confidence = output[1] if len(output) > 1 else None
        return depth, confidence
    if isinstance(output, dict):
        depth = output.get("prediction", output.get("pred_depth"))
        if depth is None:
            raise DepthEstimationError(
                "Metric3D returned a dict without a recognised depth key",
                keys=sorted(output),
            )
        return depth, output.get("confidence")
    return output, None


def _resize_confidence(
    confidence_t: Any, pad: tuple[int, int, int, int], size: tuple[int, int]
) -> NDArray[np.float32] | None:
    """Un-pad and resize the confidence map to match the depth map."""
    import torch

    try:
        conf = confidence_t.squeeze().float()
        pad_top, pad_bottom, pad_left, pad_right = pad
        conf = conf[pad_top : conf.shape[0] - pad_bottom, pad_left : conf.shape[1] - pad_right]
        conf = torch.nn.functional.interpolate(
            conf[None, None], size=size, mode="bilinear", align_corners=False
        ).squeeze()
        return conf.detach().cpu().numpy().astype(np.float32)
    except Exception as exc:  # confidence is optional metadata
        log.debug("confidence_postprocess_failed", error=str(exc))
        return None
