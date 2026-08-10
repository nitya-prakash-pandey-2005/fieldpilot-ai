"""Request correlation, timing and error translation."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from measurecv.core.exceptions import MeasureCVError
from measurecv.core.logging import bind_context, clear_context, get_logger

log = get_logger(__name__)

__all__ = ["RequestContextMiddleware", "install_exception_handlers"]


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request id, logs the outcome, and reports server timing.

    The request id is echoed in the ``X-Request-ID`` header *and* in every log
    line emitted while handling the request, so a user-reported failure can be
    traced to its logs without guessing from timestamps. An inbound
    ``X-Request-ID`` is honoured so ids survive across service hops.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        clear_context()
        bind_context(request_id=request_id, path=request.url.path, method=request.method)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000.0
            log.exception("request_failed", duration_ms=round(elapsed, 2))
            raise
        finally:
            clear_context()

        elapsed = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"total;dur={elapsed:.1f}"

        # Health checks fire constantly; logging them at info level would bury
        # everything else.
        level = log.debug if request.url.path in ("/health", "/metrics", "/ready") else log.info
        level(
            "request_complete",
            status=response.status_code,
            duration_ms=round(elapsed, 2),
            request_id=request_id,
        )
        return response


def install_exception_handlers(app: object) -> None:
    """Map the internal exception hierarchy onto structured HTTP responses."""
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)

    @app.exception_handler(MeasureCVError)
    async def _measurecv_error(request: Request, exc: MeasureCVError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        # Each exception class carries its own status code, so a calibration
        # problem reads as 422 (fix your input) rather than 500 (we broke),
        # which is the difference between an actionable and a useless error.
        log.warning(
            "domain_error",
            code=exc.code,
            message=exc.message,
            status=exc.status_code,
            **exc.context,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={**exc.to_dict(), "request_id": request_id},
        )

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.warning("value_error", message=str(exc))
        return JSONResponse(
            status_code=400,
            content={
                "code": "invalid_request",
                "message": str(exc),
                "context": {},
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.exception("unhandled_error", error=str(exc))
        # Deliberately opaque: internal messages can leak paths and config.
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "an internal error occurred; quote the request id when reporting it",
                "context": {},
                "request_id": request_id,
            },
        )
