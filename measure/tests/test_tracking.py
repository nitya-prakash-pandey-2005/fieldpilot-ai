"""Tracking tests.

Identity stability is what these protect. A single identity switch silently
merges two objects' measurement histories in the temporal smoother, producing a
confident average of two different things -- a failure that is invisible in the
output.
"""

from __future__ import annotations

import numpy as np
import pytest

from measurecv.core.config import TrackingConfig
from measurecv.core.types import BoundingBox, Detection
from measurecv.tracking.bytetrack import ByteTracker, iou_matrix
from measurecv.tracking.kalman import KalmanBoxTracker


def _detection(
    x: float, y: float, w: float = 40, h: float = 60, score: float = 0.9, label: str = "box"
) -> Detection:
    return Detection(bbox=BoundingBox(x, y, x + w, y + h), score=score, label_id=1, label=label)


class TestIouMatrix:
    def test_identical_boxes(self) -> None:
        box = [BoundingBox(0, 0, 10, 10)]
        assert iou_matrix(box, box)[0, 0] == pytest.approx(1.0)

    def test_disjoint_boxes(self) -> None:
        a = [BoundingBox(0, 0, 10, 10)]
        b = [BoundingBox(50, 50, 60, 60)]
        assert iou_matrix(a, b)[0, 0] == 0.0

    def test_empty_inputs(self) -> None:
        assert iou_matrix([], [BoundingBox(0, 0, 1, 1)]).shape == (0, 1)

    def test_matches_pairwise_method(self) -> None:
        a = [BoundingBox(0, 0, 10, 10), BoundingBox(5, 5, 15, 15)]
        b = [BoundingBox(2, 2, 12, 12)]
        matrix = iou_matrix(a, b)
        assert matrix[0, 0] == pytest.approx(a[0].iou(b[0]))
        assert matrix[1, 0] == pytest.approx(a[1].iou(b[0]))


class TestKalman:
    def test_predict_preserves_a_static_box(self) -> None:
        box = BoundingBox(100, 100, 140, 160)
        tracker = KalmanBoxTracker(box)
        for _ in range(5):
            tracker.predict()
            tracker.update(box)

        predicted = tracker.predict()

        assert predicted.centre[0] == pytest.approx(120, abs=2)
        assert predicted.centre[1] == pytest.approx(130, abs=2)

    def test_learns_constant_velocity(self) -> None:
        """After a few observations the filter should extrapolate motion."""
        tracker = KalmanBoxTracker(BoundingBox(0, 100, 40, 160))
        for step in range(1, 12):
            tracker.predict()
            tracker.update(BoundingBox(step * 10, 100, step * 10 + 40, 160))

        predicted = tracker.predict()

        assert predicted.centre[0] > 120, "should extrapolate forward motion"

    def test_ids_are_unique(self) -> None:
        a = KalmanBoxTracker(BoundingBox(0, 0, 10, 10))
        b = KalmanBoxTracker(BoundingBox(0, 0, 10, 10))
        assert a.id != b.id

    def test_survives_degenerate_area(self) -> None:
        """A shrinking box must not produce a NaN state."""
        tracker = KalmanBoxTracker(BoundingBox(0, 0, 2, 2))
        for _ in range(30):
            tracker.predict()
        assert np.isfinite(tracker.state.as_array()).all()


class TestByteTracker:
    def test_assigns_stable_ids_to_moving_object(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1, max_age=5))
        ids = []
        for step in range(12):
            tracked = tracker.update([_detection(100 + step * 6, 100)])
            assert len(tracked) == 1
            ids.append(tracked[0].track_id)

        assert len(set(ids)) == 1, f"identity switched: {ids}"

    def test_two_objects_keep_separate_ids(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1))
        first = tracker.update([_detection(50, 100), _detection(300, 100)])
        assert len({d.track_id for d in first}) == 2

        for step in range(1, 8):
            tracked = tracker.update(
                [_detection(50 + step * 4, 100), _detection(300 - step * 4, 100)]
            )

        assert len({d.track_id for d in tracked}) == 2

    def test_low_confidence_detection_keeps_track_alive(self) -> None:
        """The ByteTrack insight: a partially occluded object produces a
        low-score detection, and discarding it is what loses the identity."""
        tracker = ByteTracker(TrackingConfig(min_hits=1, max_age=10), high_threshold=0.6)

        original = tracker.update([_detection(100, 100, score=0.9)])[0].track_id
        for step in range(1, 5):
            # Simulate occlusion: score collapses but the object is still there.
            tracked = tracker.update([_detection(100 + step * 5, 100, score=0.25)])

        assert tracked, "track was lost during occlusion"
        assert tracked[0].track_id == original

    def test_track_dies_after_max_age(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1, max_age=3))
        tracker.update([_detection(100, 100)])
        for _ in range(6):
            tracker.update([])
        assert tracker.active_tracks == 0

    def test_min_hits_suppresses_flicker(self) -> None:
        """A one-frame false positive must not produce a measurement."""
        tracker = ByteTracker(TrackingConfig(min_hits=3))
        # Burn past the startup grace period.
        for _ in range(5):
            tracker.update([_detection(100, 100)])

        spurious = tracker.update([_detection(100, 100), _detection(500, 300)])

        assert all(d.bbox.x1 < 400 for d in spurious), "unconfirmed track was emitted"

    def test_predicted_detections_carry_labels(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1))
        for step in range(4):
            tracker.update([_detection(100 + step * 5, 100, label="chair")])

        predicted = tracker.predicted_detections()

        assert len(predicted) == 1
        assert predicted[0].label == "chair"
        assert predicted[0].track_id is not None
        assert predicted[0].score < 0.9, "carried score should decay"

    def test_predicted_detections_empty_without_tracks(self) -> None:
        assert ByteTracker(TrackingConfig()).predicted_detections() == []

    def test_reset_clears_everything(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1))
        tracker.update([_detection(100, 100)])
        tracker.reset()
        assert tracker.active_tracks == 0
        assert tracker.predicted_detections() == []

    def test_crossing_objects_do_not_swap(
        self,
    ) -> None:
        """Two objects passing each other is the classic identity-switch case."""
        tracker = ByteTracker(TrackingConfig(min_hits=1, max_age=10))

        left_id = None
        for step in range(20):
            left_x = 50 + step * 12
            right_x = 350 - step * 12
            tracked = tracker.update([_detection(left_x, 100), _detection(right_x, 200)])
            # Objects are separated in y, so association should stay clean.
            moving_right = [d for d in tracked if d.bbox.y1 == 100]
            if moving_right:
                if left_id is None:
                    left_id = moving_right[0].track_id
                else:
                    assert moving_right[0].track_id == left_id

    def test_handles_empty_frames(self) -> None:
        tracker = ByteTracker(TrackingConfig())
        assert tracker.update([]) == []

    def test_bootstraps_when_no_detection_clears_the_bar(self) -> None:
        """Regression: the tracker must not deadlock into permanent silence.

        Births normally require a high-confidence detection. If the detector's
        scores all sit below that bar -- a different checkpoint, a domain
        shift, an aggressive threshold -- then no track can be born, so no
        track exists, so no track can ever be born. The subsystem then emits
        nothing at all, forever, with no error raised anywhere.
        """
        tracker = ByteTracker(TrackingConfig(min_hits=1), high_threshold=0.9)

        tracked = tracker.update([_detection(100, 100, score=0.55)])

        assert tracked, "tracker produced nothing and could never recover"
        assert tracked[0].track_id is not None

    def test_bootstrap_picks_the_best_detection(self) -> None:
        tracker = ByteTracker(TrackingConfig(min_hits=1), high_threshold=0.9)

        tracked = tracker.update(
            [_detection(100, 100, score=0.30), _detection(300, 100, score=0.55)]
        )

        assert len(tracked) == 1
        assert tracked[0].bbox.x1 == 300

    def test_bootstrap_does_not_fire_once_tracking(self) -> None:
        """With a live track, low-confidence detections must sustain it rather
        than spawn new identities -- otherwise noise multiplies tracks."""
        tracker = ByteTracker(TrackingConfig(min_hits=1, max_age=5), high_threshold=0.9)
        tracker.update([_detection(100, 100, score=0.55)])

        for step in range(1, 5):
            tracker.update([_detection(100 + step * 4, 100, score=0.2)])

        assert tracker.active_tracks == 1

    def test_high_threshold_comes_from_config(self) -> None:
        tracker = ByteTracker(TrackingConfig(high_threshold=0.42))
        assert tracker._high_threshold == pytest.approx(0.42)
