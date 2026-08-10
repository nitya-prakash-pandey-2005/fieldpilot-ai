"""Latency instrumentation.

CUDA kernels are asynchronous, so a naive ``time.perf_counter()`` around a
model call measures *launch* time, not execution time. :class:`StageTimer`
synchronises the device when timing GPU stages, which is what makes the
reported per-stage breakdown trustworthy.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock

__all__ = ["RollingStats", "StageTimer", "Timer"]


@contextmanager
def Timer(sink: dict[str, float], key: str, *, sync: bool = False) -> Iterator[None]:
    """Time a block and record milliseconds into ``sink[key]``."""
    if sync:
        _sync()
    start = time.perf_counter()
    try:
        yield
    finally:
        if sync:
            _sync()
        sink[key] = sink.get(key, 0.0) + (time.perf_counter() - start) * 1000.0


def _sync() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
    except Exception:  # pragma: no cover - torch optional
        pass


@dataclass
class StageTimer:
    """Accumulates per-stage timings for one frame."""

    sync_gpu: bool = False
    timings: dict[str, float] = field(default_factory=dict)
    _t0: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        with Timer(self.timings, name, sync=self.sync_gpu):
            yield

    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def finalise(self) -> dict[str, float]:
        out = dict(self.timings)
        out["total"] = self.total_ms()
        return out


class RollingStats:
    """Thread-safe rolling window of latency samples for the metrics endpoint."""

    def __init__(self, window: int = 128) -> None:
        self._values: deque[float] = deque(maxlen=window)
        self._lock = Lock()
        self._count = 0

    def add(self, value: float) -> None:
        with self._lock:
            self._values.append(value)
            self._count += 1

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            values = sorted(self._values)
            total = self._count
        if not values:
            return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
        n = len(values)

        def pct(p: float) -> float:
            idx = min(n - 1, max(0, round(p * (n - 1))))
            return values[idx]

        return {
            "count": total,
            "mean": sum(values) / n,
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
        }
