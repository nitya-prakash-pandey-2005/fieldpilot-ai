"""
Shared Neo4j connection settings + a circuit breaker.

Two measured problems this solves, both only visible when Neo4j is NOT running
— which is exactly the state a demo laptop ends up in when Docker Desktop
didn't start:

1. `localhost` resolves to BOTH ::1 and 127.0.0.1, and the driver tries each in
   turn. A 2s connection timeout therefore costs 4s, not 2s. Defaulting the URI
   to 127.0.0.1 skips the dead IPv6 attempt outright. (The frontend hit this
   same IPv6 resolution issue earlier in the project's history.)

2. The driver connects lazily, so the cost is paid PER CALL. ComplianceEngine
   writes an Inspection node on every verdict, so a stopped container added
   ~4s to every single spoken alert — measured 5.2s for the first validate and
   4.2s for each subsequent one, against the <5s end-to-end budget in
   system_prompt.md §13.1.

The circuit breaker fixes (2): after a couple of consecutive failures it stops
attempting for a cooldown window, so the Postgres degradation paths answer
immediately. It half-opens automatically, so bringing Neo4j up mid-demo
recovers on its own within the cooldown without a restart.
"""

from __future__ import annotations

import os
import threading
import time

CONNECTION_TIMEOUT = float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "2.0"))
RETRY_TIME = float(os.getenv("NEO4J_RETRY_TIME", "2.0"))

# Spread as **DRIVER_KWARGS into GraphDatabase.driver / AsyncGraphDatabase.driver.
DRIVER_KWARGS = {
    "connection_timeout": CONNECTION_TIMEOUT,
    "max_transaction_retry_time": RETRY_TIME,
}

FAILURE_THRESHOLD = int(os.getenv("NEO4J_BREAKER_THRESHOLD", "2"))
COOLDOWN_S = float(os.getenv("NEO4J_BREAKER_COOLDOWN", "30"))


def uri() -> str:
    # 127.0.0.1, not localhost — see (1) above.
    return os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")


def auth() -> tuple[str, str]:
    return (os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "askthewall_dev"))


class _Breaker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0

    def should_attempt(self) -> bool:
        with self._lock:
            if self._failures < FAILURE_THRESHOLD:
                return True
            if time.time() - self._opened_at >= COOLDOWN_S:
                # Half-open: let one request through to test recovery. If Neo4j
                # came back, record_success() closes the breaker; if not, the
                # next failure restarts the cooldown.
                self._failures = FAILURE_THRESHOLD - 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            if self._failures:
                print("[NEO4J] connection recovered — circuit closed")
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures == FAILURE_THRESHOLD:
                self._opened_at = time.time()
                print(f"[NEO4J] unreachable after {self._failures} attempts — "
                      f"skipping Neo4j for {COOLDOWN_S:.0f}s so it stops adding "
                      f"latency to every request. Falling back to Postgres.")

    @property
    def is_open(self) -> bool:
        with self._lock:
            return (self._failures >= FAILURE_THRESHOLD
                    and time.time() - self._opened_at < COOLDOWN_S)


breaker = _Breaker()


def status() -> dict:
    return {
        "uri": uri(),
        "circuit_open": breaker.is_open,
        "connection_timeout_s": CONNECTION_TIMEOUT,
        "cooldown_s": COOLDOWN_S,
    }
