"""Structured logging.

``structlog`` is used so every log line is a machine-parsable event with
consistent keys (``request_id``, ``frame``, ``stage``, ``duration_ms``). In
production that means logs join cleanly against the Prometheus metrics; in
development a coloured console renderer keeps them readable.

The stdlib ``logging`` root is also configured so third-party libraries
(transformers, uvicorn, torch) emit through the same formatter.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars

__all__ = ["bind_context", "clear_context", "configure_logging", "get_logger", "unbind_context"]

_CONFIGURED = False


def configure_logging(
    level: str = "INFO",
    *,
    json_output: bool = False,
    quiet_libraries: bool = True,
) -> None:
    """Install structlog + stdlib logging. Idempotent.

    Args:
        level: Root log level name.
        json_output: Emit JSON lines (production) instead of console output.
        quiet_libraries: Suppress the very chatty third-party loggers.
    """
    global _CONFIGURED

    numeric = getattr(logging, level.upper(), logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    # structlog hands the event dict to stdlib *unrendered* (via
    # wrap_for_formatter) and ProcessorFormatter does the single, final render.
    # Rendering in structlog's own chain as well would emit every line twice --
    # once formatted by structlog, then again by the stdlib handler.
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # One handler renders both structlog events and records from third-party
    # libraries; foreign_pre_chain gives the latter the same enrichment.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(numeric)

    if quiet_libraries:
        for name in (
            "urllib3",
            "PIL",
            "matplotlib",
            "transformers",
            "filelock",
            "huggingface_hub",
            "asyncio",
            "multipart",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring logging on first use."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def bind_context(**kwargs: Any) -> None:
    """Attach key/values to every log line on this task/thread."""
    bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    unbind_contextvars(*keys)


def clear_context() -> None:
    clear_contextvars()
