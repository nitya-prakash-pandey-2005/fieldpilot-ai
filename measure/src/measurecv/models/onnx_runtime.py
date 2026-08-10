"""Shared ONNX Runtime session construction.

ONNX Runtime is offered as the deployment path because it removes the Python
and PyTorch dependency from the serving image (a ~4 GB saving), gives
deterministic memory use, and reaches TensorRT without a separate conversion
pipeline. Accuracy is unchanged: the export is numerically equivalent to the
PyTorch graph within float tolerance.

The provider chain is ordered TensorRT -> CUDA -> CPU, with each entry silently
skipped when unavailable, so one artefact runs everywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from measurecv.core.device import DeviceContext
from measurecv.core.exceptions import ModelLoadError
from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["create_session", "session_providers"]


def session_providers(device: DeviceContext, cache_dir: Path | None = None) -> list[Any]:
    """Provider list ordered fastest-first for the given device."""
    providers: list[Any] = []
    if device.is_cuda:
        device_id = int(device.device.split(":")[1]) if ":" in device.device else 0
        trt_options: dict[str, Any] = {
            "device_id": device_id,
            "trt_fp16_enable": device.dtype_name != "fp32",
            # Engine building is expensive (minutes); caching makes it a
            # one-time cost per model/shape rather than a per-start cost.
            "trt_engine_cache_enable": cache_dir is not None,
        }
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            trt_options["trt_engine_cache_path"] = str(cache_dir)
        providers.append(("TensorrtExecutionProvider", trt_options))
        providers.append(
            (
                "CUDAExecutionProvider",
                {
                    "device_id": device_id,
                    "arena_extend_strategy": "kSameAsRequested",
                    "cudnn_conv_algo_search": "EXHAUSTIVE",
                },
            )
        )
    providers.append("CPUExecutionProvider")
    return providers


def create_session(
    model_path: str | Path, device: DeviceContext, cache_dir: Path | None = None
) -> Any:
    """Build an inference session, keeping only providers that are installed."""
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - optional extra
        raise ModelLoadError(
            "ONNX backends need the 'onnx' extra: pip install 'measurecv[onnx]'",
            missing=str(exc),
        ) from exc

    path = Path(model_path)
    if not path.is_file():
        raise ModelLoadError(f"ONNX model not found: {path}", path=str(path))

    available = set(ort.get_available_providers())
    requested = session_providers(device, cache_dir)
    providers = [p for p in requested if (p[0] if isinstance(p, tuple) else p) in available]
    if not providers:
        providers = ["CPUExecutionProvider"]

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # The pipeline already serialises GPU work, so intra-op parallelism is what
    # helps here; spawning session threads per request would oversubscribe.
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    try:
        session = ort.InferenceSession(str(path), options, providers=providers)
    except Exception as exc:
        raise ModelLoadError(f"failed to create ONNX session for {path}: {exc}") from exc

    log.info(
        "onnx_session_created",
        path=path.name,
        providers=[p[0] if isinstance(p, tuple) else p for p in providers],
    )
    return session
