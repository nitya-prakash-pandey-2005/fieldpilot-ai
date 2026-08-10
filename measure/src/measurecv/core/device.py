"""Device and precision resolution.

Torch is imported lazily: the geometry/calibration half of the library must be
importable (and testable) on a machine with no torch installed at all.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from measurecv.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    import torch

log = get_logger(__name__)

DeviceSpec = Literal["auto", "cuda", "mps", "cpu"]
PrecisionSpec = Literal["auto", "fp32", "fp16", "bf16"]

__all__ = ["DeviceContext", "autocast_context", "empty_cache", "resolve_device", "torch_available"]


@functools.lru_cache(maxsize=1)
def torch_available() -> bool:
    """True when torch can be imported (cached -- the import is expensive)."""
    try:
        import torch  # noqa: F401 - probing importability, not using it
    except Exception:  # pragma: no cover - environment dependent
        return False
    return True


@dataclass(frozen=True, slots=True)
class DeviceContext:
    """Resolved execution target for the neural backends."""

    device: str
    dtype_name: str
    name: str = "unknown"
    total_memory_gb: float = 0.0
    supports_bf16: bool = False
    channels_last: bool = False

    @property
    def is_cuda(self) -> bool:
        return self.device.startswith("cuda")

    @property
    def torch_dtype(self) -> Any:
        import torch

        return {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[
            self.dtype_name
        ]

    @property
    def torch_device(self) -> torch.device:
        import torch

        return torch.device(self.device)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "dtype": self.dtype_name,
            "name": self.name,
            "total_memory_gb": round(self.total_memory_gb, 2),
        }


def resolve_device(
    device: DeviceSpec | str = "auto", precision: PrecisionSpec = "auto"
) -> DeviceContext:
    """Pick the best available device and a *safe* dtype for it.

    Precision policy, in order of preference on CUDA:

    * ``bf16`` on Ampere+ (compute capability >= 8.0) -- same dynamic range as
      fp32, so depth values never overflow/underflow the way they can in fp16.
    * ``fp16`` on older CUDA cards -- roughly 2x throughput, and the models
      involved are all well-behaved in half precision.
    * ``fp32`` everywhere else. Half precision on CPU is slower, not faster,
      and MPS half support is uneven, so both stay fp32 unless forced.

    This matters for accuracy: Metric3D regresses metric depth directly, and a
    silently-overflowing fp16 activation shows up as a plausible-looking but
    wrong measurement.
    """
    if not torch_available():
        if device not in ("auto", "cpu"):
            log.warning("torch_unavailable_falling_back_to_cpu", requested=device)
        return DeviceContext(device="cpu", dtype_name="fp32", name="cpu (torch unavailable)")

    import torch

    resolved = device
    if device == "auto":
        if torch.cuda.is_available():
            resolved = "cuda"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            resolved = "mps"
        else:
            resolved = "cpu"

    if resolved.startswith("cuda") and not torch.cuda.is_available():
        log.warning("cuda_requested_but_unavailable", falling_back="cpu")
        resolved = "cpu"

    name, total_gb, supports_bf16 = "cpu", 0.0, False
    if resolved.startswith("cuda"):
        idx = int(resolved.split(":")[1]) if ":" in resolved else 0
        props = torch.cuda.get_device_properties(idx)
        name = props.name
        total_gb = props.total_memory / (1024**3)
        supports_bf16 = props.major >= 8
    elif resolved == "mps":
        name = "Apple Silicon (MPS)"

    if precision == "auto":
        if resolved.startswith("cuda"):
            dtype_name = "bf16" if supports_bf16 else "fp16"
        else:
            dtype_name = "fp32"
    else:
        dtype_name = precision
        if dtype_name in ("fp16", "bf16") and not resolved.startswith("cuda"):
            log.warning("half_precision_unsupported_on_device", device=resolved, using="fp32")
            dtype_name = "fp32"

    ctx = DeviceContext(
        device=resolved,
        dtype_name=dtype_name,
        name=name,
        total_memory_gb=total_gb,
        supports_bf16=supports_bf16,
        channels_last=resolved.startswith("cuda"),
    )
    log.info("device_resolved", **ctx.to_dict())
    return ctx


def autocast_context(ctx: DeviceContext) -> Any:
    """Return an ``autocast`` context manager, or a no-op for fp32."""
    import contextlib

    import torch

    if ctx.dtype_name == "fp32" or not ctx.is_cuda:
        return contextlib.nullcontext()
    return torch.autocast(device_type="cuda", dtype=ctx.torch_dtype)


def empty_cache(ctx: DeviceContext) -> None:
    """Release cached CUDA blocks. Called after unloading a model."""
    if not ctx.is_cuda or not torch_available():
        return
    import torch

    torch.cuda.empty_cache()


def configure_torch_runtime(deterministic: bool = False, threads: int | None = None) -> None:
    """Global torch knobs applied once at process start.

    TF32 is enabled by default on Ampere+: it costs ~1e-3 relative precision on
    matmuls -- far below depth-model error -- and buys a large speedup.
    """
    if not torch_available():
        return
    import torch

    if threads is None:
        threads = int(os.environ.get("MEASURECV_TORCH_THREADS", "0")) or None
    if threads:
        torch.set_num_threads(threads)

    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = not deterministic
        torch.backends.cudnn.allow_tf32 = not deterministic
        torch.backends.cudnn.benchmark = not deterministic

    if deterministic:
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True, warn_only=True)
