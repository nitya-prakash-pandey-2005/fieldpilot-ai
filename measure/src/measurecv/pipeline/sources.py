"""Frame sources: images, video files, cameras and network streams.

One iterator interface covers all of them, so the pipeline has a single code
path for "a photo" and "an RTSP camera". The important difference between them
is not the API but the *back-pressure semantics*:

* A **file** is a pull source. If processing is slower than the file, the file
  waits. Every frame gets processed, which is what a batch job wants.
* A **live camera** is a push source. Frames arrive whether or not we are
  ready, and OpenCV buffers them. If processing is slower than the camera,
  a buffered reader returns progressively staler frames -- the classic
  "measurements lag reality by ten seconds" bug. :class:`LiveSource` therefore
  drains the buffer and always returns the newest frame instead.

That trade -- dropping frames to preserve latency -- is correct for live
measurement and wrong for offline analysis, which is why the two are separate
classes rather than a flag.
"""

from __future__ import annotations

import abc
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.core.exceptions import SourceError, UnsupportedInputError
from measurecv.core.logging import get_logger
from measurecv.core.types import Frame

log = get_logger(__name__)

__all__ = [
    "FrameSource",
    "ImageSource",
    "LiveSource",
    "VideoSource",
    "open_source",
]

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg"}


class FrameSource(abc.ABC):
    """Yields RGB frames."""

    @abc.abstractmethod
    def __iter__(self) -> Iterator[Frame]:
        """Iterate frames. Must be safe to call once."""

    @property
    def frame_count(self) -> int:
        """Total frames, or ``-1`` when unbounded/unknown."""
        return -1

    @property
    def fps(self) -> float:
        return 0.0

    @property
    def size(self) -> tuple[int, int]:
        """``(width, height)``, or ``(0, 0)`` if not yet known."""
        return (0, 0)

    def close(self) -> None:
        """Release resources. Idempotent."""

    def __enter__(self) -> FrameSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def info(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "frame_count": self.frame_count,
            "fps": round(self.fps, 3),
            "size": {"width": self.size[0], "height": self.size[1]},
        }


class ImageSource(FrameSource):
    """One or more still images."""

    def __init__(self, paths: str | Path | list[str | Path]) -> None:
        raw = [paths] if isinstance(paths, str | Path) else list(paths)
        self._paths = [Path(p) for p in raw]
        for path in self._paths:
            if not path.is_file():
                raise SourceError(f"image not found: {path}", path=str(path))
        self._size = (0, 0)

    @property
    def frame_count(self) -> int:
        return len(self._paths)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def __iter__(self) -> Iterator[Frame]:
        for index, path in enumerate(self._paths):
            image = read_image(path)
            self._size = (image.shape[1], image.shape[0])
            yield Frame(image=image, index=index, timestamp=time.time(), source_id=str(path))


class VideoSource(FrameSource):
    """A video file. Every frame is delivered; the reader blocks as needed."""

    def __init__(
        self,
        path: str | Path,
        *,
        start_frame: int = 0,
        max_frames: int | None = None,
        stride: int = 1,
    ) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise SourceError(f"video not found: {self._path}", path=str(self._path))

        self._capture = cv2.VideoCapture(str(self._path))
        if not self._capture.isOpened():
            raise UnsupportedInputError(
                f"cannot decode video: {self._path}. Check the codec is supported by your "
                "OpenCV build (H.264 often needs a full FFmpeg build).",
                path=str(self._path),
            )

        self._stride = max(1, stride)
        self._max_frames = max_frames
        self._start = max(0, start_frame)
        if self._start:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, self._start)

    @property
    def frame_count(self) -> int:
        total = int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            return -1
        remaining = max(0, total - self._start)
        available = (remaining + self._stride - 1) // self._stride
        return min(available, self._max_frames) if self._max_frames else available

    @property
    def fps(self) -> float:
        value = float(self._capture.get(cv2.CAP_PROP_FPS))
        # Some containers report 0 or absurd values; fall back to a sane rate
        # so downstream timestamp arithmetic stays finite.
        return value if 0.0 < value < 1000.0 else 30.0

    @property
    def size(self) -> tuple[int, int]:
        return (
            int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def __iter__(self) -> Iterator[Frame]:
        emitted = 0
        raw_index = self._start
        fps = self.fps
        while True:
            ok, bgr = self._capture.read()
            if not ok:
                break
            if (raw_index - self._start) % self._stride == 0:
                yield Frame(
                    image=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB),
                    index=raw_index,
                    timestamp=raw_index / fps,
                    source_id=str(self._path),
                )
                emitted += 1
                if self._max_frames and emitted >= self._max_frames:
                    break
            raw_index += 1

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()


class LiveSource(FrameSource):
    """A camera index or network stream, read newest-frame-first.

    A background thread continuously drains the capture so the OpenCV buffer
    never accumulates. Consumers always see the most recent frame, and stale
    frames are dropped rather than queued.
    """

    def __init__(
        self,
        source: int | str,
        *,
        width: int | None = None,
        height: int | None = None,
        target_fps: float | None = None,
        reconnect: bool = True,
        max_reconnect_attempts: int = 10,
    ) -> None:
        self._source = source
        self._reconnect = reconnect
        self._max_attempts = max_reconnect_attempts
        self._requested = (width, height)
        self._target_fps = target_fps

        self._capture = self._open()
        self._latest: tuple[NDArray[np.uint8], float] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._frames_read = 0
        self._frames_dropped = 0

        self._thread = threading.Thread(target=self._reader, name="live-source", daemon=True)
        self._thread.start()

    def _open(self) -> cv2.VideoCapture:
        capture = cv2.VideoCapture(self._source)
        if not capture.isOpened():
            raise SourceError(
                f"cannot open live source: {self._source}. For a camera check the index and "
                "that no other process holds the device; for a URL check the network and codec.",
                source=str(self._source),
            )
        width, height = self._requested
        if width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # Ask the driver for the smallest possible buffer. Not all backends
        # honour it, which is why the reader thread drains as well.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _reader(self) -> None:
        attempts = 0
        while not self._stop.is_set():
            ok, bgr = self._capture.read()
            if not ok:
                if not self._reconnect or attempts >= self._max_attempts:
                    log.error("live_source_lost", source=str(self._source), attempts=attempts)
                    break
                attempts += 1
                wait = min(30.0, 2.0**attempts * 0.1)  # exponential backoff
                log.warning("live_source_reconnecting", attempt=attempts, wait_s=round(wait, 2))
                self._stop.wait(wait)
                try:
                    self._capture.release()
                    self._capture = self._open()
                except SourceError:
                    continue
                continue

            attempts = 0
            self._frames_read += 1
            with self._lock:
                if self._latest is not None:
                    self._frames_dropped += 1
                self._latest = (cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), time.time())

    @property
    def size(self) -> tuple[int, int]:
        return (
            int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    @property
    def fps(self) -> float:
        value = float(self._capture.get(cv2.CAP_PROP_FPS))
        return value if 0.0 < value < 1000.0 else 30.0

    @property
    def stats(self) -> dict[str, int]:
        return {"frames_read": self._frames_read, "frames_dropped": self._frames_dropped}

    def __iter__(self) -> Iterator[Frame]:
        index = 0
        min_interval = 1.0 / self._target_fps if self._target_fps else 0.0
        last_emit = 0.0

        while not self._stop.is_set():
            with self._lock:
                latest = self._latest
                self._latest = None  # consume, so we never re-emit a stale frame

            if latest is None:
                if not self._thread.is_alive():
                    break
                time.sleep(0.002)
                continue

            now = time.monotonic()
            if min_interval and (now - last_emit) < min_interval:
                continue
            last_emit = now

            image, timestamp = latest
            yield Frame(image=image, index=index, timestamp=timestamp, source_id=str(self._source))
            index += 1

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()


def read_image(path: str | Path) -> NDArray[np.uint8]:
    """Read an image file as RGB.

    ``cv2.imdecode`` on raw bytes is used rather than ``cv2.imread`` because
    the latter cannot open paths containing non-ASCII characters on Windows.
    """
    p = Path(path)
    try:
        data = np.fromfile(str(p), dtype=np.uint8)
    except OSError as exc:
        raise SourceError(f"cannot read {p}: {exc}", path=str(p)) from exc

    if data.size == 0:
        raise UnsupportedInputError(f"empty file: {p}", path=str(p))

    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise UnsupportedInputError(f"unsupported or corrupt image: {p}", path=str(p))
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def decode_image_bytes(data: bytes) -> NDArray[np.uint8]:
    """Decode an uploaded image payload to RGB."""
    if not data:
        raise UnsupportedInputError("empty upload")
    array = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if bgr is None:
        raise UnsupportedInputError(
            "could not decode the uploaded image; supported formats are "
            "JPEG, PNG, BMP, WebP and TIFF"
        )
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def open_source(spec: str | int | Path, **kwargs: Any) -> FrameSource:
    """Build the right source for a path, URL, or camera index.

    Dispatch rules:

    * ``int``, or a digit string -> camera index (live)
    * ``rtsp://``/``http://``/``https://`` -> network stream (live)
    * an image suffix -> :class:`ImageSource`
    * a video suffix -> :class:`VideoSource`
    * a directory -> all images inside it, sorted
    """
    if isinstance(spec, int):
        return LiveSource(spec, **kwargs)

    text = str(spec)
    if text.isdigit():
        return LiveSource(int(text), **kwargs)
    if text.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://")):
        return LiveSource(text, **kwargs)

    path = Path(text)
    if path.is_dir():
        images = sorted(p for p in path.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)
        if not images:
            raise SourceError(f"no images found in {path}", path=str(path))
        return ImageSource(list(images))

    suffix = path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return ImageSource(path)
    if suffix in _VIDEO_SUFFIXES:
        return VideoSource(path, **kwargs)

    raise UnsupportedInputError(
        f"cannot determine how to open '{spec}'. Supported: image files "
        f"({', '.join(sorted(_IMAGE_SUFFIXES))}), video files "
        f"({', '.join(sorted(_VIDEO_SUFFIXES))}), a directory of images, "
        "a camera index, or an rtsp:// / http:// stream URL.",
        spec=text,
    )
