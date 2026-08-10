"""Live capture with measurement decoupled from display.

The problem
-----------
A full measurement is expensive -- on CPU with real weights it is *seconds*
per frame. Running it inline with capture gives a preview that updates once
every few seconds: technically live, unusable in practice, and it looks broken.

The fix is to stop conflating two different rates. The camera produces frames
at 15-30 fps and the display should keep up with it. Measurement is a slower,
independent process whose latest result is *overlaid* onto whatever frame is
current. The video stays smooth, the numbers refresh when they are ready, and
the pipeline is never the thing making the picture stutter.

That trade has a real consequence, so it is surfaced rather than hidden: an
overlay can describe a frame that is a second or two old. :class:`LiveResult`
carries the measurement's age, the renderer shows it, and a reading taken
mid-movement is therefore attributable instead of mysterious.

Threads
-------
* **Capture** -- owned by :class:`~measurecv.pipeline.sources.LiveSource`,
  which already drains the driver buffer so frames never go stale in a queue.
* **Worker** -- pulls the newest frame, measures it, publishes the result.
  Exactly one, because the models are the bottleneck and a second worker would
  contend for the same GPU/CPU rather than add throughput.
* **Consumer** -- the caller's loop (an OpenCV window, an MJPEG response, a
  WebSocket) which reads the newest frame and newest result and composes them.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from measurecv.core.exceptions import MeasureCVError
from measurecv.core.logging import get_logger
from measurecv.core.types import Frame, InstanceMask, SceneMeasurement

if TYPE_CHECKING:  # pragma: no cover
    from measurecv.calibration.intrinsics import CameraIntrinsics
    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import FrameSource

log = get_logger(__name__)

__all__ = ["LiveResult", "LiveSession", "LiveStats"]


@dataclass(slots=True)
class LiveResult:
    """A measurement plus the context needed to render it honestly."""

    scene: SceneMeasurement
    masks: list[InstanceMask]
    intrinsics: CameraIntrinsics
    frame_index: int
    produced_at: float
    latency_ms: float

    @property
    def age_s(self) -> float:
        """Seconds since this measurement was produced.

        The renderer shows this. An overlay describing a two-second-old frame
        is fine when the camera is still and misleading when it is not, and the
        viewer is the one who knows which.
        """
        return time.monotonic() - self.produced_at


@dataclass(slots=True)
class LiveStats:
    """Counters for the status line."""

    frames_displayed: int = 0
    frames_measured: int = 0
    frames_skipped: int = 0
    """Captured frames the worker never saw because it was busy. Expected and
    healthy -- it is what keeps the display smooth."""
    errors: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _latencies: list[float] = field(default_factory=list)

    def record_latency(self, ms: float) -> None:
        self._latencies.append(ms)
        if len(self._latencies) > 30:
            self._latencies.pop(0)

    @property
    def elapsed_s(self) -> float:
        return max(1e-6, time.monotonic() - self.started_at)

    @property
    def display_fps(self) -> float:
        return self.frames_displayed / self.elapsed_s

    @property
    def measure_fps(self) -> float:
        return self.frames_measured / self.elapsed_s

    @property
    def mean_latency_ms(self) -> float:
        return float(np.mean(self._latencies)) if self._latencies else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames_displayed": self.frames_displayed,
            "frames_measured": self.frames_measured,
            "frames_skipped": self.frames_skipped,
            "errors": self.errors,
            "display_fps": round(self.display_fps, 2),
            "measure_fps": round(self.measure_fps, 3),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
        }


class LiveSession:
    """Runs a source and a measurement worker at independent rates.

    Usage::

        with LiveSession(pipeline, source) as session:
            for frame, result in session.stream():
                display(compose(frame, result))
    """

    def __init__(
        self,
        pipeline: MeasurementPipeline,
        source: FrameSource,
        *,
        track: bool = True,
        measure: bool = True,
    ) -> None:
        self._pipeline = pipeline
        self._source = source
        self._track = track
        self._measure = measure

        self._latest_frame: Frame | None = None
        self._latest_result: LiveResult | None = None
        self._frame_lock = threading.Lock()
        self._result_lock = threading.Lock()
        self._new_frame = threading.Event()
        self._stop = threading.Event()

        self._worker: threading.Thread | None = None
        self.stats = LiveStats()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._worker is not None:
            return
        self._stop.clear()
        self.stats = LiveStats()
        if self._measure:
            self._worker = threading.Thread(
                target=self._measure_loop, name="live-measure", daemon=True
            )
            self._worker.start()
            log.info("live_session_started", track=self._track)

    def stop(self) -> None:
        self._stop.set()
        self._new_frame.set()  # wake the worker so it can exit
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=30.0)
        self._worker = None
        log.info("live_session_stopped", **self.stats.to_dict())

    def __enter__(self) -> LiveSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
        self._source.close()

    # -- public API --------------------------------------------------------
    @property
    def latest_result(self) -> LiveResult | None:
        with self._result_lock:
            return self._latest_result

    def wait_for_result(self, timeout: float = 60.0) -> LiveResult | None:
        """Block until a measurement newer than the current one is available.

        The streaming loop is intentionally non-blocking, but some callers do
        want a single answer -- "measure what the camera sees now" for a
        snapshot endpoint, or a test that must not race the worker. This is the
        supported way to wait, rather than sleeping and hoping.

        Returns:
            The new result, or ``None`` if the timeout elapsed first.
        """
        with self._result_lock:
            baseline = self._latest_result

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                break
            current = self.latest_result
            if current is not None and current is not baseline:
                return current
            time.sleep(0.02)
        return None

    def stream(self) -> Iterator[tuple[Frame, LiveResult | None]]:
        """Yield every captured frame with the most recent measurement.

        The result may be ``None`` before the first measurement completes, and
        will often describe an earlier frame. That is the design -- check
        ``result.age_s`` if it matters for your use.
        """
        for frame in self._source:
            if self._stop.is_set():
                break

            with self._frame_lock:
                if self._latest_frame is not None:
                    self.stats.frames_skipped += 1
                self._latest_frame = frame
            self._new_frame.set()

            self.stats.frames_displayed += 1
            yield frame, self.latest_result

    # -- worker ------------------------------------------------------------
    def _measure_loop(self) -> None:
        while not self._stop.is_set():
            # Wait for work rather than spinning; the timeout lets the thread
            # notice a stop request even if the camera has gone quiet.
            if not self._new_frame.wait(timeout=0.5):
                continue
            self._new_frame.clear()

            with self._frame_lock:
                frame = self._latest_frame
                self._latest_frame = None
            if frame is None or self._stop.is_set():
                continue

            started = time.perf_counter()
            try:
                artifacts = self._pipeline.measure_frame_full(frame, track=self._track)
            except MeasureCVError as exc:
                self.stats.errors += 1
                log.warning("live_measure_failed", index=frame.index, error=str(exc))
                continue
            except Exception as exc:  # a worker death would silently end measuring
                self.stats.errors += 1
                log.exception("live_measure_crashed", error=str(exc))
                continue

            latency = (time.perf_counter() - started) * 1000.0
            self.stats.frames_measured += 1
            self.stats.record_latency(latency)

            with self._result_lock:
                self._latest_result = LiveResult(
                    scene=artifacts.scene,
                    masks=artifacts.masks,
                    intrinsics=artifacts.intrinsics,
                    frame_index=frame.index,
                    produced_at=time.monotonic(),
                    latency_ms=latency,
                )


def compose_live_frame(
    frame: Frame,
    result: LiveResult | None,
    stats: LiveStats,
    *,
    style: Any = None,
    stale_after_s: float = 1.5,
) -> NDArray[np.uint8]:
    """Draw the latest measurement over the current frame, with its age.

    Masks are only drawn while the result is fresh. A mask is a pixel-exact
    claim about *a specific frame*; painting a two-second-old one over a moved
    scene looks like a segmentation failure rather than the latency it actually
    is. Boxes and numbers still show, dimmed, because a slightly stale
    dimension is still useful information.
    """
    import cv2

    from measurecv.viz.annotate import AnnotationStyle, draw_scene

    # Keep the top strip clear so labels never sit under the status line.
    style = style or AnnotationStyle(show_volume=True)
    style.reserved_top_px = max(style.reserved_top_px, 22)
    canvas = frame.image

    if result is not None:
        age = result.age_s
        fresh = age <= stale_after_s
        canvas = draw_scene(
            frame.image,
            result.scene,
            masks=[m.mask for m in result.masks] if fresh else None,
            intrinsics=result.intrinsics,
            style=style,
        )
    else:
        # Nothing measured yet. On CPU the first result is ~30 s away -- model
        # load plus one inference -- so say what is happening. A bare camera
        # feed for half a minute is indistinguishable from a hang.
        canvas = frame.image.copy()
        height, width = canvas.shape[:2]
        message = "loading models, then measuring"
        (tw, th), _ = cv2.getTextSize(message, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2)
        x, y = max(10, (width - tw) // 2), height // 2
        cv2.rectangle(canvas, (x - 14, y - th - 12), (x + tw + 40, y + 14), (18, 18, 18), -1)
        # A moving ellipsis makes it obvious the app is alive, not frozen.
        dots = "." * (int(time.monotonic() * 2) % 4)
        cv2.putText(
            canvas,
            message + dots,
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 220, 80),
            2,
            cv2.LINE_AA,
        )

    _draw_live_status(canvas, result, stats, stale_after_s)
    return canvas


def _draw_live_status(
    canvas: NDArray[np.uint8],
    result: LiveResult | None,
    stats: LiveStats,
    stale_after_s: float,
) -> None:
    """Status strip: display rate, measurement rate, and overlay age."""
    import cv2

    parts = [
        f"view {stats.display_fps:.0f}fps",
        f"measure {stats.measure_fps:.2f}fps ({stats.mean_latency_ms / 1000:.1f}s)",
    ]
    colour = (200, 220, 200)
    if result is not None:
        age = result.age_s
        parts.append(f"overlay {age:.1f}s old")
        if age > stale_after_s:
            colour = (255, 190, 80)
    if stats.errors:
        parts.append(f"{stats.errors} err")

    text = "  |  ".join(parts)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.rectangle(canvas, (0, 0), (tw + 14, th + 12), (18, 18, 18), -1)
    cv2.putText(canvas, text, (7, th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
