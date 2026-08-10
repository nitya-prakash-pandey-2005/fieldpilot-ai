"""ByteTrack-style multi-object tracking.

Tracking exists here to serve *measurement*, not display. Its job is to give
each physical object a stable identity so that
:class:`~measurecv.measurement.temporal.TemporalSmoother` can fuse observations
across frames. A single identity switch silently merges two objects'
measurement histories, so identity stability matters more than the usual
detection-oriented MOT metrics.

The ByteTrack insight is that low-confidence detections are usually *real
objects that are partially occluded*, not noise. Discarding them (as plain
SORT does) is precisely what causes identity loss during occlusion -- the very
moment when maintaining identity matters most. The two-stage association below
matches confident detections first, then offers the leftover tracks a second
chance against the low-confidence pool.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from measurecv.core.config import TrackingConfig
from measurecv.core.logging import get_logger
from measurecv.core.types import BoundingBox, Detection
from measurecv.tracking.kalman import KalmanBoxTracker

log = get_logger(__name__)

__all__ = ["ByteTracker", "iou_matrix"]


def iou_matrix(a: Sequence[BoundingBox], b: Sequence[BoundingBox]) -> NDArray[np.float64]:
    """Pairwise IoU, vectorised."""
    if not a or not b:
        return np.zeros((len(a), len(b)))

    boxes_a = np.array([box.as_tuple() for box in a], dtype=np.float64)
    boxes_b = np.array([box.as_tuple() for box in b], dtype=np.float64)

    x1 = np.maximum(boxes_a[:, None, 0], boxes_b[None, :, 0])
    y1 = np.maximum(boxes_a[:, None, 1], boxes_b[None, :, 1])
    x2 = np.minimum(boxes_a[:, None, 2], boxes_b[None, :, 2])
    y2 = np.minimum(boxes_a[:, None, 3], boxes_b[None, :, 3])

    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(union > 0, inter / union, 0.0)


def _associate(
    tracks: Sequence[BoundingBox],
    detections: Sequence[BoundingBox],
    threshold: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Optimal one-to-one assignment by IoU.

    The Hungarian algorithm is used rather than greedy matching: greedy
    produces different results depending on iteration order and can lock in a
    poor early pair that forces two later objects to swap identities.

    Returns:
        ``(matches, unmatched_track_indices, unmatched_detection_indices)``.
    """
    if not tracks or not detections:
        return [], list(range(len(tracks))), list(range(len(detections)))

    ious = iou_matrix(tracks, detections)
    row_idx, col_idx = linear_sum_assignment(-ious)

    matches: list[tuple[int, int]] = []
    matched_tracks: set[int] = set()
    matched_detections: set[int] = set()

    for r, c in zip(row_idx, col_idx, strict=True):
        # The assignment is globally optimal but may still pair boxes that do
        # not overlap; the threshold is what rejects those.
        if ious[r, c] >= threshold:
            matches.append((int(r), int(c)))
            matched_tracks.add(int(r))
            matched_detections.add(int(c))

    unmatched_tracks = [i for i in range(len(tracks)) if i not in matched_tracks]
    unmatched_detections = [i for i in range(len(detections)) if i not in matched_detections]
    return matches, unmatched_tracks, unmatched_detections


class ByteTracker:
    """Two-stage IoU tracker with Kalman motion prediction."""

    def __init__(self, config: TrackingConfig, high_threshold: float | None = None) -> None:
        """Args:
        config: Age/hit/IoU parameters, including ``high_threshold``.
        high_threshold: Overrides the configured value. Detections at or
            above it are "confident" and eligible for first-stage
            association and for spawning new tracks.
        """
        self._config = config
        self._high_threshold = (
            high_threshold if high_threshold is not None else config.high_threshold
        )
        self._trackers: list[KalmanBoxTracker] = []
        self._frame_count = 0
        # Class identity is a property of the object, not of the motion filter,
        # so it is kept here rather than inside the Kalman state.
        self._labels: dict[int, tuple[int, str, float]] = {}

    @property
    def active_tracks(self) -> int:
        return len(self._trackers)

    def reset(self) -> None:
        self._trackers.clear()
        self._labels.clear()
        self._frame_count = 0

    def predicted_detections(self) -> list[Detection]:
        """Current tracks as detections, using the Kalman prediction as the box.

        This is what makes ``runtime.detect_every_n_frames > 1`` viable: on
        frames where RT-DETR is skipped, the motion model supplies boxes good
        enough to prompt SAM 2, which then produces a fresh, pixel-accurate
        mask. Detection is the expensive stage and object identity changes
        slowly; mask quality is what measurement actually depends on, and that
        is still computed every frame.
        """
        output: list[Detection] = []
        for tracker in self._trackers:
            meta = self._labels.get(tracker.id)
            if meta is None or tracker.time_since_update > 1:
                continue
            label_id, label, score = meta
            box = tracker.state
            if box.width <= 0 or box.height <= 0:
                continue
            output.append(
                Detection(
                    bbox=box,
                    # Decay the carried score so a track coasting on prediction
                    # is visibly less trustworthy than a fresh detection.
                    score=score * 0.95,
                    label_id=label_id,
                    label=label,
                    track_id=tracker.id,
                )
            )
        return output

    def update(self, detections: Sequence[Detection]) -> list[Detection]:
        """Assign track ids, returning the detections that belong to live tracks.

        Detections are returned with ``track_id`` populated. Tracks in their
        probationary period (fewer than ``min_hits`` observations) are withheld
        so a one-frame false positive never produces a measurement -- except
        during the first few frames, where withholding everything would make
        short clips return nothing at all.
        """
        self._frame_count += 1
        cfg = self._config

        # Advance every track and drop any whose predicted box is degenerate.
        predicted: list[BoundingBox] = []
        alive: list[KalmanBoxTracker] = []
        for tracker in self._trackers:
            box = tracker.predict()
            if np.isfinite(box.as_array()).all() and box.width > 0 and box.height > 0:
                predicted.append(box)
                alive.append(tracker)
        self._trackers = alive

        high = [d for d in detections if d.score >= self._high_threshold]
        low = [d for d in detections if d.score < self._high_threshold]

        # Bootstrap. New tracks are only ever born from the high-confidence
        # pool, which is correct while tracking is under way -- it stops noise
        # from spawning tracks. But if *nothing* clears the bar and there is
        # nothing to track, that rule deadlocks: no births are possible, so no
        # tracks exist, so no births are possible. The subsystem then produces
        # zero output forever with no error anywhere, which is exactly the kind
        # of silent failure this codebase tries to avoid.
        #
        # It is reachable in practice whenever a detector's score calibration
        # sits below `high_threshold` -- a different checkpoint, a domain shift,
        # or simply a threshold set too aggressively. When there is nothing to
        # lose, seed from the best evidence available instead.
        if not high and low and not self._trackers:
            best = max(d.score for d in low)
            high = [d for d in low if d.score >= best - 1e-9]
            low = [d for d in low if d.score < best - 1e-9]
            log.debug(
                "tracker_bootstrapped_from_low_confidence",
                score=round(best, 4),
                threshold=self._high_threshold,
                hint="detector scores sit below tracking.high_threshold; consider lowering it",
            )

        # -- stage 1: confident detections ---------------------------------
        matches, unmatched_tracks, unmatched_high = _associate(
            predicted, [d.bbox for d in high], cfg.iou_threshold
        )
        for track_idx, det_idx in matches:
            self._trackers[track_idx].update(high[det_idx].bbox)
            high[det_idx].track_id = self._trackers[track_idx].id

        # -- stage 2: leftover tracks vs low-confidence detections ---------
        # A lower IoU bar is used here: these boxes are typically partially
        # occluded, so their overlap with the prediction is genuinely reduced
        # and the stage-1 threshold would reject valid recoveries.
        if unmatched_tracks and low:
            remaining = [predicted[i] for i in unmatched_tracks]
            low_matches, still_unmatched, _ = _associate(
                remaining, [d.bbox for d in low], cfg.iou_threshold * 0.5
            )
            for local_idx, det_idx in low_matches:
                global_idx = unmatched_tracks[local_idx]
                self._trackers[global_idx].update(low[det_idx].bbox)
                low[det_idx].track_id = self._trackers[global_idx].id
            unmatched_tracks = [unmatched_tracks[i] for i in still_unmatched]

        # -- births: only from confident detections ------------------------
        for det_idx in unmatched_high:
            tracker = KalmanBoxTracker(high[det_idx].bbox)
            self._trackers.append(tracker)
            high[det_idx].track_id = tracker.id

        # -- deaths --------------------------------------------------------
        self._trackers = [t for t in self._trackers if t.time_since_update <= cfg.max_age]

        by_id = {t.id: t for t in self._trackers}
        for detection in [*high, *low]:
            if detection.track_id is not None and detection.track_id in by_id:
                self._labels[detection.track_id] = (
                    detection.label_id,
                    detection.label,
                    detection.score,
                )
        for track_id in list(self._labels):
            if track_id not in by_id:
                del self._labels[track_id]

        output: list[Detection] = []
        for detection in [*high, *low]:
            if detection.track_id is None:
                continue
            owner = by_id.get(detection.track_id)
            if owner is None:
                continue
            confirmed = owner.hits >= cfg.min_hits or self._frame_count <= cfg.min_hits
            if confirmed and owner.time_since_update == 0:
                output.append(detection)

        output.sort(key=lambda d: d.score, reverse=True)
        return output
