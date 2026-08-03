"""
Live stream ingestion — the glasses-to-cloud path.

The worker's phone relays the glasses feed by publishing RTMP to the media
server; this module consumes that stream, decides which frames are worth
analysing, runs the vision pipeline on those, and emits results.

Three things here are production concerns rather than demo concerns, and each
one is the difference between a pipeline that works for 30 seconds and one that
works for a shift:

1. YOU MUST DRAIN THE DECODER.
   Duty-cycling means analysing one frame every N seconds. The naive
   implementation sleeps between reads — and then the decoder's buffer fills,
   so every frame you eventually read is from minutes ago and latency grows
   without bound. This reads continuously and *discards* frames it isn't
   analysing, so the frame it does analyse is always current.

2. RECONNECTION IS THE NORMAL CASE.
   Construction WiFi drops constantly. A stream reader that exits on failure is
   useless. This reconnects with exponential backoff and keeps running.

3. DECODE FAILURES ARE NOT STREAM FAILURES.
   A corrupt packet on a lossy link returns a bad read while the stream is
   perfectly alive. Treating one failed read as a disconnect causes thrashing,
   so consecutive failures are counted before declaring the stream down.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import cv2

# Analyse one frame every this many seconds. The pitch deck's figure is 5s; it
# is a real tradeoff, not a magic number — longer means less compute and less
# battery on the relay phone, but a hazard can persist unnoticed for that long.
DEFAULT_ANALYSIS_INTERVAL_S = float(os.getenv("STREAM_ANALYSIS_INTERVAL_S", "5.0"))

# Consecutive failed reads before we treat the stream as gone. At ~30fps this is
# about a third of a second of corruption, which a lossy link produces routinely.
MAX_CONSECUTIVE_READ_FAILURES = 10

RECONNECT_BACKOFF_S = [1, 2, 4, 8, 15, 30]


@dataclass
class StreamStats:
    frames_received: int = 0
    frames_analysed: int = 0
    frames_dropped: int = 0          # read and discarded by duty-cycling
    read_failures: int = 0
    reconnects: int = 0
    last_frame_at: Optional[str] = None
    last_analysis_at: Optional[str] = None
    last_error: Optional[str] = None
    mean_analysis_ms: Optional[float] = None
    connected: bool = False
    started_at: Optional[str] = None
    _analysis_times: list[float] = field(default_factory=list, repr=False)

    def record_analysis(self, ms: float) -> None:
        self.frames_analysed += 1
        self.last_analysis_at = datetime.now(timezone.utc).isoformat()
        self._analysis_times.append(ms)
        if len(self._analysis_times) > 50:
            self._analysis_times.pop(0)
        self.mean_analysis_ms = round(sum(self._analysis_times) / len(self._analysis_times), 1)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        # Duty cycle actually achieved, which is the honest measure of whether
        # the configured interval is being met under real load.
        total = self.frames_received or 1
        d["analysis_ratio"] = round(self.frames_analysed / total, 4)
        return d


class StreamIngestor:
    """Consumes one live stream in a background thread.

    on_analysis(result, frame, meta) is called for each analysed frame. It runs
    on the ingest thread, so it must not block for long — push to a queue or an
    HTTP call with a short timeout, don't do heavy work inline.
    """

    def __init__(self,
                 stream_url: str,
                 worker_id: str,
                 zone_id: str = "A12",
                 analysis_interval_s: float = DEFAULT_ANALYSIS_INTERVAL_S,
                 on_analysis: Optional[Callable[[dict, "cv2.Mat", dict], None]] = None,
                 pipeline=None):
        self.stream_url = stream_url
        self.worker_id = worker_id
        self.zone_id = zone_id
        self.analysis_interval_s = max(0.1, analysis_interval_s)
        self.on_analysis = on_analysis
        self.stats = StreamStats()

        self._pipeline = pipeline
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cap: Optional[cv2.VideoCapture] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.stats.started_at = datetime.now(timezone.utc).isoformat()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=f"ingest-{self.worker_id}")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self.stats.connected = False

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- internals ---------------------------------------------------------

    def _get_pipeline(self):
        if self._pipeline is None:
            from agents.vision.detector import VisionPipeline
            self._pipeline = VisionPipeline(zone_id=self.zone_id)
        return self._pipeline

    def _open(self) -> bool:
        # CAP_FFMPEG explicitly: OpenCV would otherwise probe backends and can
        # pick one without network support depending on the build.
        cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return False
        # Smallest possible buffer. Combined with continuous draining below,
        # this is what keeps the analysed frame current rather than minutes old.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass                        # not supported on every backend
        self._cap = cap
        return True

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            if not self._open():
                self.stats.connected = False
                self.stats.last_error = f"could not open {self.stream_url}"
                delay = RECONNECT_BACKOFF_S[min(attempt, len(RECONNECT_BACKOFF_S) - 1)]
                attempt += 1
                # Interruptible wait: a stop() during backoff must take effect
                # immediately rather than after the full delay.
                if self._stop.wait(delay):
                    break
                continue

            self.stats.connected = True
            self.stats.last_error = None
            if attempt:
                self.stats.reconnects += 1
            attempt = 0
            self._consume()

        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.stats.connected = False

    def _consume(self) -> None:
        """Read continuously; analyse on the duty cycle."""
        last_analysis = 0.0
        failures = 0

        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                failures += 1
                self.stats.read_failures += 1
                if failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    self.stats.last_error = "stream ended or too many decode failures"
                    break
                time.sleep(0.02)
                continue

            failures = 0
            self.stats.frames_received += 1
            self.stats.last_frame_at = datetime.now(timezone.utc).isoformat()

            now = time.time()
            if now - last_analysis < self.analysis_interval_s:
                # Deliberately discarded. This is the duty cycle: the read still
                # happened, which is what keeps the decoder drained and the next
                # analysed frame current.
                self.stats.frames_dropped += 1
                continue

            last_analysis = now
            t0 = time.time()
            try:
                result = self._get_pipeline().analyze_ndarray(frame)
            except Exception as e:
                self.stats.last_error = f"analysis failed: {e}"
                continue
            self.stats.record_analysis((time.time() - t0) * 1000)

            if self.on_analysis is not None:
                try:
                    self.on_analysis(result, frame, {
                        "worker_id": self.worker_id,
                        "zone_id": self.zone_id,
                        "stream_url": self.stream_url,
                        "frame_index": self.stats.frames_received,
                    })
                except Exception as e:
                    # A consumer failure must not kill ingestion.
                    self.stats.last_error = f"on_analysis raised: {e}"

        if self._cap is not None:
            self._cap.release()
            self._cap = None


class IngestManager:
    """Registry of running ingestors, keyed by worker."""

    def __init__(self):
        self._ingestors: dict[str, StreamIngestor] = {}
        self._lock = threading.Lock()

    def start(self, worker_id: str, stream_url: str, zone_id: str = "A12",
              analysis_interval_s: float = DEFAULT_ANALYSIS_INTERVAL_S,
              on_analysis=None) -> StreamIngestor:
        with self._lock:
            existing = self._ingestors.get(worker_id)
            if existing is not None:
                existing.stop()
            ing = StreamIngestor(stream_url, worker_id, zone_id,
                                 analysis_interval_s, on_analysis)
            self._ingestors[worker_id] = ing
        ing.start()
        return ing

    def stop(self, worker_id: str) -> bool:
        with self._lock:
            ing = self._ingestors.pop(worker_id, None)
        if ing is None:
            return False
        ing.stop()
        return True

    def stop_all(self) -> int:
        with self._lock:
            items = list(self._ingestors.items())
            self._ingestors.clear()
        for _, ing in items:
            ing.stop()
        return len(items)

    def get(self, worker_id: str) -> Optional[StreamIngestor]:
        return self._ingestors.get(worker_id)

    def status(self) -> dict:
        return {
            "active": sum(1 for i in self._ingestors.values() if i.running),
            "streams": {
                wid: {"stream_url": i.stream_url, "zone_id": i.zone_id,
                      "running": i.running,
                      "analysis_interval_s": i.analysis_interval_s,
                      **i.stats.as_dict()}
                for wid, i in self._ingestors.items()
            },
        }


manager = IngestManager()
