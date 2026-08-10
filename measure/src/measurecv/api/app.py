"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from measurecv import __version__
from measurecv.api.deps import AppState
from measurecv.api.middleware import RequestContextMiddleware, install_exception_handlers
from measurecv.api.routers import calibration, measure, stream, system
from measurecv.core.config import AppConfig, load_config
from measurecv.core.device import configure_torch_runtime
from measurecv.core.logging import configure_logging, get_logger

log = get_logger(__name__)

__all__ = ["create_app"]

_DESCRIPTION = """
Metric object measurement from RGB images, video and live camera streams.

**Pipeline:** RT-DETR detection -> SAM 2 segmentation -> Metric3D metric depth
-> camera-calibrated geometric reconstruction.

### Reading the results

Every quantity is returned as `{value, sigma, unit, confidence, interval_95}`.

* `sigma` is a **1-sigma physical error bar** derived from the propagated error
  budget (depth scale, focal length, pixel localisation, sample count).
* `confidence` is a separate **method-applicability score** in [0, 1]. High
  sigma means "wide error bar"; low confidence means "the assumptions behind
  this method may not hold here". Check both.
* `calibration_source` tells you where the camera model came from. `calibrated`
  is good for roughly 1-2% accuracy; `exif` for ~5%; **`assumed_fov` means no
  calibration was available and absolute scale may be off by ~15%.**

### Getting the best accuracy

1. Calibrate the camera (`POST /v1/calibration/intrinsics`) -- the single
   largest improvement available.
2. Include a known reference object and refine scale
   (`POST /v1/calibration/scale`).
3. Keep objects fully inside the frame; truncated objects are flagged and
   their measurements are lower bounds.
"""


def create_app(config: AppConfig | None = None) -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton so tests can construct
    isolated apps with different configuration, and so ``uvicorn --factory``
    can control creation order.
    """
    config = config or load_config()
    configure_logging(config.log_level, json_output=config.log_json)
    configure_torch_runtime(
        deterministic=config.runtime.deterministic, threads=config.runtime.torch_threads
    )

    state = AppState(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.app_state = state
        log.info(
            "api_starting",
            version=__version__,
            device=state.pipeline.models.device.device,
            backends={
                "detection": config.detection.backend,
                "segmentation": config.segmentation.backend,
                "depth": config.depth.backend,
            },
        )
        if not config.api.api_keys:
            log.warning(
                "api_authentication_disabled",
                impact="all endpoints are open, including the server-side MJPEG source",
                fix="set api.api_keys or MEASURECV__API__API_KEYS before exposing this service",
            )
        # Loading happens in a worker thread so the event loop can start
        # serving /health immediately; readiness flips when it completes.
        import asyncio

        await asyncio.to_thread(state.startup)
        try:
            yield
        finally:
            state.shutdown()

    app = FastAPI(
        title="measurecv",
        version=__version__,
        description=_DESCRIPTION,
        lifespan=lifespan,
        root_path=config.api.root_path,
        docs_url="/docs" if config.api.enable_docs else None,
        redoc_url="/redoc" if config.api.enable_docs else None,
        openapi_url="/openapi.json" if config.api.enable_docs else None,
    )

    # Order matters: the request-context middleware must be outermost so its
    # request id is bound before anything else runs or logs.
    app.add_middleware(RequestContextMiddleware)
    # Measurement payloads are verbose JSON and compress by roughly 10x.
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Server-Timing"],
    )

    install_exception_handlers(app)

    app.include_router(system.router)
    app.include_router(measure.router)
    app.include_router(calibration.router)
    app.include_router(stream.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "name": "measurecv",
            "version": __version__,
            "docs": "/docs" if config.api.enable_docs else None,
            "health": "/health",
            "measure": "/v1/measure",
        }

    return app


def run() -> None:
    """Entry point for ``python -m measurecv.api.app``."""
    import uvicorn

    config = load_config()
    uvicorn.run(
        create_app(config),
        host=config.api.host,
        port=config.api.port,
        # Access logging is handled by RequestContextMiddleware, which adds the
        # request id and structured fields uvicorn's logger lacks.
        access_log=False,
        timeout_keep_alive=30,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
