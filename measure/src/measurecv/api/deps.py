"""Shared application state and FastAPI dependencies.

The pipeline is a process-wide singleton because it owns GPU weights: creating
one per request would exhaust memory immediately, and creating one per worker
is why ``api.workers > 1`` is rejected on CUDA in the configuration validator.
"""

from __future__ import annotations

import secrets
import time
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status

from measurecv.core.config import AppConfig, load_config
from measurecv.core.logging import get_logger
from measurecv.pipeline.pipeline import MeasurementPipeline

log = get_logger(__name__)

__all__ = ["AppState", "get_config", "get_pipeline", "get_state", "require_api_key"]


class AppState:
    """Holds everything with a process lifetime."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.started_at = time.time()
        self.pipeline = MeasurementPipeline(self.config)
        self.ready = False

    @property
    def uptime_s(self) -> float:
        return time.time() - self.started_at

    def startup(self) -> None:
        """Load and warm the models so readiness is meaningful."""
        try:
            if self.config.runtime.warmup:
                self.pipeline.warmup()
            self.ready = True
            log.info("api_ready", uptime_s=round(self.uptime_s, 2))
        except Exception as exc:
            # Stay up and serve /health and /calibrate; measurement endpoints
            # will surface the real error. Crashing the process on a model
            # failure would take down a deployment that is still 90% useful.
            log.error("startup_incomplete", error=str(exc), exc_info=True)
            self.ready = False

    def shutdown(self) -> None:
        self.pipeline.models.release_all()
        log.info("api_shutdown")


def get_state(request: Request) -> AppState:
    """The application state attached at startup."""
    state: AppState | None = getattr(request.app.state, "app_state", None)
    if state is None:  # pragma: no cover - only if the lifespan did not run
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="application state is not initialised",
        )
    return state


def get_pipeline(state: Annotated[AppState, Depends(get_state)]) -> MeasurementPipeline:
    return state.pipeline


def get_config(state: Annotated[AppState, Depends(get_state)]) -> AppConfig:
    return state.config


def require_api_key(
    state: Annotated[AppState, Depends(get_state)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Enforce ``X-API-Key`` when keys are configured.

    Authentication is opt-in: an empty key list leaves the API open, which is
    the right default for a sidecar on a private network and the wrong one for
    a public deployment -- hence the startup warning in :mod:`measurecv.api.app`.
    """
    keys = state.config.api.api_keys
    if not keys:
        return
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # Constant-time comparison against every key: a plain `in` check leaks key
    # length and prefix through timing.
    if not any(secrets.compare_digest(x_api_key, key) for key in keys):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid API key")


def enforce_upload_limit(state: AppState, size_bytes: int, filename: str) -> None:
    """Reject oversized uploads with a clear message."""
    limit = state.config.api.max_upload_mb * 1024 * 1024
    if size_bytes > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"'{filename}' is {size_bytes / 1e6:.1f} MB, above the "
                f"{state.config.api.max_upload_mb:.0f} MB limit"
            ),
        )


def summarise_state(state: AppState) -> dict[str, Any]:
    """Snapshot for the health endpoint."""
    stats = state.pipeline.stats()
    return {
        "uptime_s": round(state.uptime_s, 2),
        "ready": state.ready,
        "frames_processed": stats["frames_processed"],
        "latency_ms": stats["latency_ms"],
        "device": state.pipeline.models.device.to_dict(),
    }
