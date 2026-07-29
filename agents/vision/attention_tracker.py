"""
Attention Tracker — FieldPilot AI
------------------------------------
Tracks how long a worker has (or hasn't) acknowledged an active hazard by
watching sustained gaze direction over time, driving the three-state
machine called for in the Master Execution Plan, Day 4:

  PASSIVE      -> a hazard is active for this worker; no sustained
                  acknowledging gaze yet. A brief glance does NOT count —
                  see MIN_DWELL_SECONDS (the dwell-vs-glance refinement).
  ACKNOWLEDGED -> the worker held a "looking at the task/hazard area" gaze
                  for at least MIN_DWELL_SECONDS while the hazard was active.
  ESCALATED    -> the hazard has been active for at least
                  IGNORE_TIMEOUT_SECONDS with no acknowledging gaze at all.

Honest limitation: a fully faithful implementation would check gaze against
a hazard's actual 3D position (a real gaze vector intersected with the
hazard's location) — that needs depth + full head pose, which isn't in
scope. This uses head-yaw-within-a-forward-looking-band (already computed
by PoseEstimator as `looking_away`) as a proxy for "attending to the task
in front of them." That's a deliberate, documented stand-in, not a claim of
precise spatial gaze-to-hazard targeting — flagged here so it's never
confused with the real thing later.
"""

from typing import Optional

MIN_DWELL_SECONDS = 0.8       # sustained "looking at task" gaze needed to count as acknowledged, not a glance
IGNORE_TIMEOUT_SECONDS = 4.0  # hazard unacknowledged this long -> escalate

PASSIVE = "PASSIVE"
ACKNOWLEDGED = "ACKNOWLEDGED"
ESCALATED = "ESCALATED"


class _WorkerAttentionRecord:
    __slots__ = ("state", "hazard_first_seen_ts", "gaze_ok_since_ts")

    def __init__(self, timestamp: float, looking_away: bool):
        self.state = PASSIVE
        self.hazard_first_seen_ts = timestamp
        self.gaze_ok_since_ts: Optional[float] = None if looking_away else timestamp


class AttentionStateMachine:
    """
    Per-track_id PASSIVE -> ACKNOWLEDGED -> ESCALATED state machine.

    Call update() once per frame per worker. `timestamp` is caller-supplied
    (not read from wall-clock internally), so this is fully unit-testable
    with a scripted sequence and no real sleeps — the same pattern already
    used for fall-confirmation timing in pose_estimator.py's _hip_history.
    """

    def __init__(self):
        self._records: dict[int, _WorkerAttentionRecord] = {}

    def update(self, track_id: Optional[int], looking_away: bool, hazard_active: bool, timestamp: float) -> str:
        if track_id is None:
            return PASSIVE  # can't track sustained attention without a stable identity

        if not hazard_active:
            # Nothing to attend to right now — clear so a future hazard
            # starts its own fresh PASSIVE -> ... timeline instead of
            # inheriting a stale dwell/ignore clock.
            self._records.pop(track_id, None)
            return PASSIVE

        record = self._records.get(track_id)
        if record is None:
            record = _WorkerAttentionRecord(timestamp, looking_away)
            self._records[track_id] = record
        else:
            # Track (or break) the current "looking at task" streak.
            if looking_away:
                record.gaze_ok_since_ts = None
            elif record.gaze_ok_since_ts is None:
                record.gaze_ok_since_ts = timestamp

        dwell = (timestamp - record.gaze_ok_since_ts) if record.gaze_ok_since_ts is not None else 0.0
        ignored_for = timestamp - record.hazard_first_seen_ts

        if record.state != ACKNOWLEDGED and dwell >= MIN_DWELL_SECONDS:
            record.state = ACKNOWLEDGED
        elif record.state == PASSIVE and ignored_for >= IGNORE_TIMEOUT_SECONDS:
            record.state = ESCALATED
        # Note: ESCALATED can still upgrade to ACKNOWLEDGED via the dwell
        # check above — a worker who eventually notices, even late, should
        # be recorded as having acknowledged it.

        return record.state

    def reset_track(self, track_id: int):
        """Clear state for a lost track (mirrors PoseEstimator.reset_track)."""
        self._records.pop(track_id, None)
