"""Health, readiness, metrics and model introspection.

Liveness and readiness are separated deliberately. Kubernetes restarts a
container that fails liveness and merely stops routing traffic to one that
fails readiness. Reporting "not ready" while a multi-gigabyte checkpoint loads
is correct; reporting "not alive" would make the orchestrator kill the process
partway through loading, forever.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from measurecv import __version__
from measurecv.api.deps import AppState, get_state, require_api_key
from measurecv.api.metrics import get_metrics
from measurecv.api.schemas import HealthResponse, ModelsResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and status")
async def health(state: Annotated[AppState, Depends(get_state)]) -> dict[str, Any]:
    """Always 200 while the process is alive; ``status`` carries the detail."""
    stats = state.pipeline.stats()
    return {
        "status": "ok" if state.ready else "starting",
        "version": __version__,
        "uptime_s": round(state.uptime_s, 2),
        "device": state.pipeline.models.device.to_dict(),
        "models_loaded": state.ready,
        "frames_processed": stats["frames_processed"],
        "latency_ms": {k: round(v, 2) for k, v in stats["latency_ms"].items()},
    }


@router.get("/ready", summary="Readiness for traffic")
async def ready(
    state: Annotated[AppState, Depends(get_state)], response: Response
) -> dict[str, Any]:
    """503 until the models are loaded and warmed."""
    if not state.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"ready": False, "reason": "models are still loading"}
    return {"ready": True}


@router.get("/metrics", summary="Prometheus exposition", include_in_schema=False)
async def metrics(state: Annotated[AppState, Depends(get_state)]) -> Response:
    if not state.config.api.enable_metrics:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    registry = get_metrics()
    for name, model in (
        ("detector", state.pipeline.models._detector),
        ("segmenter", state.pipeline.models._segmenter),
        ("depth", state.pipeline.models._depth),
    ):
        registry.set_model_loaded(name, bool(model and model.is_loaded))

    payload, content_type = registry.render()
    return Response(content=payload, media_type=content_type)


@router.get(
    "/v1/models",
    response_model=ModelsResponse,
    summary="Backend and device information",
    dependencies=[Depends(require_api_key)],
)
async def models(state: Annotated[AppState, Depends(get_state)]) -> dict[str, Any]:
    """Which backends are configured, and whether their weights are resident."""
    return state.pipeline.models.info()


@router.get(
    "/v1/config", summary="Effective configuration", dependencies=[Depends(require_api_key)]
)
async def effective_config(state: Annotated[AppState, Depends(get_state)]) -> dict[str, Any]:
    """The running configuration, with secrets removed.

    Invaluable for debugging "it behaves differently in production" -- which is
    almost always an environment-variable override nobody remembered.
    """
    payload = state.config.model_dump(mode="json")
    payload.get("api", {}).pop("api_keys", None)
    return payload
