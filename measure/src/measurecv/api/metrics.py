"""Prometheus metrics.

Metric choice is driven by what an operator needs to answer at 3am:

* *Is it up and serving?* -- request counter by status.
* *Is it slow, and which stage?* -- per-stage latency histograms. A single
  end-to-end timer cannot distinguish "the GPU is thrashing" from "someone is
  uploading 40-megapixel images".
* *Are the numbers any good?* -- a confidence histogram and a counter of
  objects that failed to measure. Silent quality regressions (a mis-set
  calibration profile, a camera knocked out of focus) show up here long before
  anyone files a bug.

``prometheus_client`` is optional: if it is absent every function degrades to a
no-op rather than taking down the service.
"""

from __future__ import annotations

from typing import Any

from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["MetricsRegistry", "get_metrics"]

try:
    from prometheus_client import (  # type: ignore[import-not-found]
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover - optional extra
    _AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"


#: Buckets tuned for this workload: sub-100 ms is unattainable for the full
#: three-model stack, and anything past ~10 s is a timeout, not a latency.
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)


class MetricsRegistry:
    """Typed wrapper so call sites never test for availability."""

    def __init__(self) -> None:
        self.enabled = _AVAILABLE
        if not _AVAILABLE:
            return

        self.requests = Counter("measurecv_requests_total", "HTTP requests", ["endpoint", "status"])
        self.request_latency = Histogram(
            "measurecv_request_duration_seconds",
            "End-to-end request latency",
            ["endpoint"],
            buckets=_LATENCY_BUCKETS,
        )
        self.stage_latency = Histogram(
            "measurecv_stage_duration_seconds",
            "Per-pipeline-stage latency",
            ["stage"],
            buckets=_LATENCY_BUCKETS,
        )
        self.objects_measured = Counter(
            "measurecv_objects_measured_total", "Objects successfully measured"
        )
        self.objects_failed = Counter(
            "measurecv_objects_failed_total", "Objects detected but not measurable", ["reason"]
        )
        self.confidence = Histogram(
            "measurecv_measurement_confidence",
            "Composite confidence of emitted measurements",
            buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
        )
        self.relative_error = Histogram(
            "measurecv_relative_uncertainty",
            "Reported 1-sigma relative uncertainty of the largest dimension",
            buckets=(0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5),
        )
        self.active_streams = Gauge("measurecv_active_streams", "Live stream sessions")
        self.models_loaded = Gauge("measurecv_models_loaded", "Loaded models", ["model"])

    # -- recording ---------------------------------------------------------
    def record_request(self, endpoint: str, status: int, duration_s: float) -> None:
        if not self.enabled:
            return
        self.requests.labels(endpoint=endpoint, status=str(status)).inc()
        self.request_latency.labels(endpoint=endpoint).observe(duration_s)

    def record_scene(self, scene: Any) -> None:
        """Record measurement-quality metrics for one frame."""
        if not self.enabled:
            return

        for stage, milliseconds in scene.timings_ms.items():
            self.stage_latency.labels(stage=stage).observe(milliseconds / 1000.0)

        for obj in scene.objects:
            if obj.dimensions is None:
                reason = _failure_reason(obj.warnings)
                self.objects_failed.labels(reason=reason).inc()
                continue
            self.objects_measured.inc()
            self.confidence.observe(obj.confidence)
            largest = max(
                (obj.dimensions.length, obj.dimensions.width, obj.dimensions.height),
                key=lambda m: m.value,
            )
            if largest.value > 0:
                self.relative_error.observe(min(largest.relative_error, 1.0))

    def set_model_loaded(self, model: str, loaded: bool) -> None:
        if self.enabled:
            self.models_loaded.labels(model=model).set(1.0 if loaded else 0.0)

    def render(self) -> tuple[bytes, str]:
        """Return the exposition payload and its content type."""
        if not self.enabled:
            return (
                b"# prometheus_client is not installed; install measurecv[api] to enable metrics\n",
                "text/plain",
            )
        return generate_latest(), CONTENT_TYPE_LATEST


def _failure_reason(warnings: list[str]) -> str:
    """Bucket a warning into a low-cardinality metric label.

    Free-text warnings must never become label values -- unbounded cardinality
    is the classic way to melt a Prometheus server.
    """
    joined = " ".join(warnings).lower()
    if "truncat" in joined or "border" in joined:
        return "truncated"
    if "not measurable" in joined or "insufficient" in joined or "survived" in joined:
        return "insufficient_points"
    if "shape fit" in joined or "degenerate" in joined:
        return "degenerate_geometry"
    if "back-projection" in joined:
        return "backprojection_failed"
    return "other"


_REGISTRY: MetricsRegistry | None = None


def get_metrics() -> MetricsRegistry:
    """Process-wide registry. Prometheus collectors may only be created once."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MetricsRegistry()
        if not _REGISTRY.enabled:
            log.info("metrics_disabled", reason="prometheus_client not installed")
    return _REGISTRY
