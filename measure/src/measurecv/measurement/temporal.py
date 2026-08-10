"""Temporal fusion of per-frame measurements.

Two things happen here, and they are often conflated:

* **Smoothing** -- a per-frame measurement of a static object jitters by a few
  percent. Averaging over a track removes that jitter and makes the displayed
  number stable enough to read.

* **Uncertainty reduction** -- averaging ``n`` observations reduces *random*
  error by ``sqrt(n)``. It does **not** reduce systematic error. Watching a box
  for ten minutes with a mis-estimated focal length yields a very precise wrong
  answer, and the reported sigma must not collapse towards zero and imply
  otherwise.

The implementation therefore tracks the two error components separately and
floors the fused sigma at the systematic level.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from measurecv.core.config import TrackingConfig
from measurecv.core.logging import get_logger
from measurecv.core.types import Dimensions, Measured, ObjectMeasurement, SceneMeasurement

log = get_logger(__name__)

__all__ = ["TemporalSmoother", "TrackState"]


@dataclass(slots=True)
class _Channel:
    """Running state for one scalar quantity of one track."""

    window: deque[float]
    ema: float | None = None
    systematic_floor: float = 0.0
    """The smallest sigma this channel may report, carried from the first
    observation's systematic component."""

    def update(self, value: float, mode: str, alpha: float) -> float:
        self.window.append(value)
        if mode == "median":
            return float(np.median(self.window))
        if mode == "ema":
            self.ema = value if self.ema is None else alpha * value + (1 - alpha) * self.ema
            return float(self.ema)
        return value

    @property
    def count(self) -> int:
        return len(self.window)

    @property
    def dispersion(self) -> float:
        """Observed standard deviation -- an empirical repeatability estimate,
        which is often more honest than the analytic model.
        """
        return float(np.std(self.window)) if len(self.window) > 1 else 0.0


@dataclass(slots=True)
class TrackState:
    """Accumulated measurement history for one tracked object."""

    track_id: int
    label: str
    channels: dict[str, _Channel] = field(default_factory=dict)
    observations: int = 0
    last_frame: int = -1

    def channel(self, name: str, window: int) -> _Channel:
        channel = self.channels.get(name)
        if channel is None:
            channel = _Channel(window=deque(maxlen=window))
            self.channels[name] = channel
        return channel


class TemporalSmoother:
    """Fuses measurements across frames, keyed by track id.

    Untracked objects (``track_id is None``) pass through unchanged: without an
    identity there is nothing to fuse, and averaging across different objects
    would be worse than no smoothing at all.
    """

    def __init__(self, config: TrackingConfig, systematic_fraction: float = 0.8) -> None:
        """Args:
        config: Smoothing mode, window and EMA weight.
        systematic_fraction: Fraction of a single-frame sigma attributed to
            systematic sources. 0.8 reflects the error budget: for a
            typical monocular setup, metric-scale and focal error dominate
            the random terms, so most of the error bar cannot be averaged
            away.
        """
        self._config = config
        self._systematic_fraction = systematic_fraction
        self._tracks: dict[int, TrackState] = {}

    @property
    def tracks(self) -> dict[int, TrackState]:
        return self._tracks

    def reset(self) -> None:
        self._tracks.clear()

    def prune(self, active_ids: set[int]) -> None:
        """Drop state for tracks that no longer exist."""
        for track_id in list(self._tracks):
            if track_id not in active_ids:
                del self._tracks[track_id]

    def update(self, scene: SceneMeasurement) -> SceneMeasurement:
        """Return the scene with smoothed measurements substituted in place."""
        if self._config.smoothing == "none":
            return scene

        for obj in scene.objects:
            track_id = obj.track_id
            if track_id is None:
                continue
            state = self._tracks.get(track_id)
            if state is None:
                state = TrackState(track_id=track_id, label=obj.detection.label)
                self._tracks[track_id] = state
            state.observations += 1
            state.last_frame = scene.frame_index
            self._smooth_object(obj, state)

        self.prune({o.track_id for o in scene.objects if o.track_id is not None})
        return scene

    # -- internals ---------------------------------------------------------
    def _smooth_object(self, obj: ObjectMeasurement, state: TrackState) -> None:
        if obj.dimensions is not None:
            obj.dimensions = Dimensions(
                length=self._smooth(obj.dimensions.length, state, "length"),
                width=self._smooth(obj.dimensions.width, state, "width"),
                height=self._smooth(obj.dimensions.height, state, "height"),
                axes=obj.dimensions.axes,
                origin=obj.dimensions.origin,
            )
        if obj.volume is not None:
            obj.volume = self._smooth(obj.volume, state, "volume")
        if obj.surface_area is not None:
            obj.surface_area = self._smooth(obj.surface_area, state, "surface_area")
        if obj.footprint_area is not None:
            obj.footprint_area = self._smooth(obj.footprint_area, state, "footprint_area")
        if obj.distance is not None:
            obj.distance = self._smooth(obj.distance, state, "distance")
        if obj.nearest_distance is not None:
            obj.nearest_distance = self._smooth(obj.nearest_distance, state, "nearest_distance")

        obj.extras["observations"] = state.observations

    def _smooth(self, m: Measured, state: TrackState, name: str) -> Measured:
        cfg = self._config
        channel = state.channel(name, cfg.smoothing_window)

        if channel.systematic_floor == 0.0 and m.sigma > 0:
            channel.systematic_floor = m.sigma * self._systematic_fraction

        value = channel.update(m.value, cfg.smoothing, cfg.smoothing_alpha)
        n = max(1, channel.count)

        # Split the single-frame sigma, average down only the random half.
        systematic = channel.systematic_floor or m.sigma * self._systematic_fraction
        random_part = math.sqrt(max(0.0, m.sigma**2 - systematic**2))
        fused_random = random_part / math.sqrt(n)

        # If the track's own frame-to-frame spread exceeds the model's random
        # prediction, believe the data: observed instability is real evidence
        # that the measurement is less repeatable than the model assumed.
        observed = channel.dispersion / math.sqrt(n) if n > 1 else 0.0
        fused_random = max(fused_random, observed)

        sigma = math.hypot(systematic, fused_random)

        # Confidence grows with corroborating observations but saturates --
        # more frames of the same viewpoint do not resolve an ambiguous shape.
        confidence = min(1.0, m.confidence * (1.0 + 0.08 * math.log1p(n - 1)))

        return Measured(value, sigma, m.unit, m.method, confidence)
