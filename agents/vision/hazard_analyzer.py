"""
Hazard Analyzer — FieldPilot AI
---------------------------------
Fuses signals from:
  - PPE detector   (hardhat / vest presence)
  - Pose estimator (fall detection, body angle, head yaw)
  - Zone context   (restricted area proximity — future)

Produces a scored HazardAssessment object (0–100) per worker
and fires structured alert events for downstream notification.

Risk levels:
  90-100  → CRITICAL (fall, no PPE + moving)
  70-89   → HIGH     (no PPE stationary, or near-fall)
  40-69   → ELEVATED (looking away from work, minor PPE gap)
  0-39    → NORMAL
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from agents.vision.attention_tracker import AttentionStateMachine, PASSIVE, ESCALATED, IGNORE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HazardAssessment:
    worker_id: str
    track_id: Optional[int]
    zone_id: str
    timestamp: float

    # PPE signals
    hardhat_present: bool = True
    vest_present: bool = True
    ppe_compliant: bool = True
    ppe_violations: list[str] = field(default_factory=list)

    # Pose signals
    fall_detected: bool = False
    fall_confidence: float = 0.0
    body_angle_deg: float = 0.0
    head_yaw_deg: float = 0.0
    looking_away: bool = False
    attention_state: str = PASSIVE  # PASSIVE | ACKNOWLEDGED | ESCALATED (see attention_tracker.py)

    # Struck-by signals (agents/vision/equipment_detector.py) — one of
    # OSHA's construction "Focus Four" hazard categories, alongside falls
    # (pose) and PPE, both already covered above.
    struck_by_risk: bool = False
    nearest_equipment_type: Optional[str] = None
    nearest_equipment_distance_px: Optional[float] = None

    # Scored output
    hazard_score: int = 0          # 0–100
    risk_level: str = "normal"     # normal | elevated | high | critical
    primary_alert: str = ""        # human-readable primary issue
    all_warnings: list[str] = field(default_factory=list)

    # Trigger flags for event bus
    fire_fall_alert: bool = False
    fire_ppe_alert: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scorer weights
# ---------------------------------------------------------------------------

WEIGHT_FALL_CONFIRMED = 95
WEIGHT_FALL_NEAR = 55           # high body angle but not confirmed yet
WEIGHT_NO_HARDHAT = 50
WEIGHT_NO_VEST = 20
WEIGHT_LOOKING_AWAY = 10
WEIGHT_BOTH_PPE_MISSING = 20    # extra penalty when both are missing
WEIGHT_ESCALATED_ATTENTION = 25  # extra penalty when a hazard has gone unacknowledged too long
WEIGHT_STRUCK_BY_PROXIMITY = 45  # worker within STRUCK_BY_PROXIMITY_PX of moving equipment


# ---------------------------------------------------------------------------
# HazardAnalyzer
# ---------------------------------------------------------------------------

class HazardAnalyzer:
    """
    Scorer — call analyze() per frame per person.
    Can also be used in a batch mode via analyze_frame().

    The score computation itself is stateless per call, but attention
    tracking (Day 4 — PASSIVE/ACKNOWLEDGED/ESCALATED) inherently needs
    dwell-time history across frames. Callers own an AttentionStateMachine
    instance (create once, reuse across frames, same convention as
    PoseEstimator's own internal per-track_id history) and pass it in;
    HazardAnalyzer itself still holds no state of its own.
    """

    def analyze(
        self,
        *,
        worker_id: str,
        track_id: Optional[int],
        zone_id: str,
        ppe_status: dict,
        pose_result: Optional[dict] = None,
        attention_tracker: Optional[AttentionStateMachine] = None,
        timestamp: Optional[float] = None,
        nearby_equipment: Optional[tuple[float, dict]] = None,
    ) -> HazardAssessment:
        """
        Produce a HazardAssessment for a single worker.

        Args:
            worker_id:   Logical worker identifier (e.g. "WRK-001").
            track_id:    BoT-SORT track id from current frame.
            zone_id:     Zone the worker is currently in.
            ppe_status:  Output from PpeDetector.check_worker().
            pose_result: Output from PoseEstimator.analyze_frame() for this person (optional).
            attention_tracker: Shared AttentionStateMachine to drive the
                Day-4 attention state machine; omitted means attention
                stays PASSIVE (no dwell-time tracking).
            timestamp:   Inject a specific timestamp (for testing the
                attention state machine on a scripted sequence without real
                sleeps); defaults to time.time().
            nearby_equipment: (distance_px, equipment_dict) tuple from
                EquipmentDetector.nearest_equipment_distance() for this
                worker, or None if no equipment was detected in frame.

        Returns:
            HazardAssessment dataclass.
        """
        ts = timestamp if timestamp is not None else time.time()
        assessment = HazardAssessment(
            worker_id=worker_id,
            track_id=track_id,
            zone_id=zone_id,
            timestamp=ts,
        )

        # ---- PPE signals ------------------------------------------------
        assessment.hardhat_present = ppe_status.get("hardhat", True)
        assessment.vest_present = ppe_status.get("vest", True)
        assessment.ppe_compliant = ppe_status.get("compliant", True)
        assessment.ppe_violations = ppe_status.get("violations", [])

        # ---- Pose signals -----------------------------------------------
        if pose_result:
            assessment.fall_detected = pose_result.get("fall_detected", False)
            assessment.fall_confidence = pose_result.get("fall_confidence", 0.0)
            assessment.body_angle_deg = pose_result.get("body_angle_deg", 0.0)
            assessment.head_yaw_deg = pose_result.get("head_yaw_deg", 0.0)
            assessment.looking_away = pose_result.get("looking_away", False)

        # ---- Struck-by signals (heavy equipment proximity) --------------
        if nearby_equipment is not None:
            distance_px, equipment = nearby_equipment
            from agents.vision.equipment_detector import STRUCK_BY_PROXIMITY_PX
            assessment.nearest_equipment_type = equipment.get("equipment_type")
            assessment.nearest_equipment_distance_px = round(distance_px, 1)
            assessment.struck_by_risk = distance_px < STRUCK_BY_PROXIMITY_PX

        # ---- Score computation ------------------------------------------
        score = 0
        warnings = list(ppe_status.get("violations", []))

        if pose_result:
            warnings.extend(pose_result.get("warnings", []))

        # Fall
        if assessment.fall_detected:
            score += WEIGHT_FALL_CONFIRMED
            warnings.insert(0, "⚠ FALL DETECTED — IMMEDIATE RESPONSE REQUIRED")
        elif assessment.body_angle_deg > 50:
            score += WEIGHT_FALL_NEAR
            warnings.append(f"NEAR-FALL: body angle {assessment.body_angle_deg:.0f}°")

        # Struck-by (heavy equipment proximity)
        if assessment.struck_by_risk:
            score += WEIGHT_STRUCK_BY_PROXIMITY
            warnings.insert(0, f"⚠ STRUCK-BY RISK — {assessment.nearest_equipment_type} within {assessment.nearest_equipment_distance_px:.0f}px")

        # PPE
        if not assessment.hardhat_present:
            score += WEIGHT_NO_HARDHAT
        if not assessment.vest_present:
            score += WEIGHT_NO_VEST
        if not assessment.hardhat_present and not assessment.vest_present:
            score += WEIGHT_BOTH_PPE_MISSING   # compounding penalty

        # Attention (instantaneous — did the worker glance away this frame)
        if assessment.looking_away:
            score += WEIGHT_LOOKING_AWAY

        # Attention (sustained — Day 4 dwell-time state machine). A hazard is
        # "active" for attention-tracking purposes whenever something is
        # already flagged above (fall risk or a PPE gap) — i.e. there is a
        # condition worth the worker actually attending to right now.
        hazard_active = score > 0
        if attention_tracker is not None:
            assessment.attention_state = attention_tracker.update(
                track_id=track_id,
                looking_away=assessment.looking_away,
                hazard_active=hazard_active,
                timestamp=ts,
            )
        if assessment.attention_state == ESCALATED:
            score += WEIGHT_ESCALATED_ATTENTION
            warnings.append(f"⚠ HAZARD UNACKNOWLEDGED — worker has not looked at it in {IGNORE_TIMEOUT_SECONDS:.0f}s+")

        # Clamp
        score = min(score, 100)
        assessment.hazard_score = score

        # ---- Risk level ------------------------------------------------
        if score >= 90:
            assessment.risk_level = "critical"
        elif score >= 70:
            assessment.risk_level = "high"
        elif score >= 40:
            assessment.risk_level = "elevated"
        else:
            assessment.risk_level = "normal"

        # ---- Primary alert message -------------------------------------
        if assessment.fall_detected:
            assessment.primary_alert = f"FALL DETECTED — Worker {worker_id} down in Zone {zone_id}"
        elif assessment.struck_by_risk:
            assessment.primary_alert = f"STRUCK-BY RISK — Worker {worker_id} near {assessment.nearest_equipment_type} in Zone {zone_id}"
        elif not assessment.hardhat_present and not assessment.vest_present:
            assessment.primary_alert = f"Worker {worker_id}: No hardhat AND no vest in Zone {zone_id}"
        elif not assessment.hardhat_present:
            assessment.primary_alert = f"Worker {worker_id}: Missing hardhat in Zone {zone_id}"
        elif not assessment.vest_present:
            assessment.primary_alert = f"Worker {worker_id}: Missing hi-vis vest in Zone {zone_id}"
        elif assessment.attention_state == ESCALATED:
            assessment.primary_alert = f"Worker {worker_id}: hazard unacknowledged for {IGNORE_TIMEOUT_SECONDS:.0f}s+ in Zone {zone_id}"
        elif assessment.looking_away:
            assessment.primary_alert = f"Worker {worker_id} not looking at work area"
        else:
            assessment.primary_alert = f"Worker {worker_id} — Zone {zone_id}: Normal"

        assessment.all_warnings = warnings

        # ---- Alert triggers ---------------------------------------------
        assessment.fire_fall_alert = assessment.fall_detected
        assessment.fire_ppe_alert = not assessment.ppe_compliant

        return assessment

    def analyze_frame(
        self,
        *,
        zone_id: str,
        persons: list[dict],
        pose_results: list[dict],
        attention_tracker: Optional[AttentionStateMachine] = None,
        timestamp: Optional[float] = None,
        equipment: Optional[list[dict]] = None,
    ) -> list[HazardAssessment]:
        """
        Batch-analyze all persons detected in a frame.

        Args:
            zone_id:      Zone identifier.
            persons:      list of asset dicts from the primary detector.
                          Each must have 'asset_id', optional 'track_id', 'ppe_status'.
            pose_results: list of results from PoseEstimator.analyze_frame().
                          Matched to persons by track_id; uses positional index as fallback.
            attention_tracker: Shared AttentionStateMachine (create once per
                pipeline/camera, reuse every frame) to drive Day-4 attention
                state; omitted means attention stays PASSIVE.
            timestamp:    Inject a specific timestamp for testing; defaults
                to time.time() per-person inside analyze().
            equipment:    list of detections from EquipmentDetector.detect()
                for this frame, or None/[] if unavailable — struck-by
                scoring is simply skipped in that case.

        Returns:
            list of HazardAssessment objects (one per person).
        """
        from agents.vision.equipment_detector import EquipmentDetector
        # Build pose lookup by track_id
        pose_by_track: dict[int, dict] = {}
        for pr in pose_results:
            tid = pr.get("track_id")
            if tid is not None:
                pose_by_track[tid] = pr

        assessments = []
        for i, person in enumerate(persons):
            track_id = person.get("track_id")
            worker_id = person.get("asset_id", f"WRK-{i+1:03d}")
            ppe_status = person.get("ppe_status", {
                "hardhat": True, "vest": True, "compliant": True, "violations": []
            })

            # Match pose result
            pose_result = None
            if track_id is not None and track_id in pose_by_track:
                pose_result = pose_by_track[track_id]
            elif i < len(pose_results):
                pose_result = pose_results[i]

            nearby_equipment = None
            if equipment:
                nearby_equipment = EquipmentDetector.nearest_equipment_distance(
                    person.get("bounding_box", {}), equipment
                )

            assessment = self.analyze(
                worker_id=worker_id,
                track_id=track_id,
                zone_id=zone_id,
                ppe_status=ppe_status,
                pose_result=pose_result,
                attention_tracker=attention_tracker,
                timestamp=timestamp,
                nearby_equipment=nearby_equipment,
            )
            assessments.append(assessment)

        return assessments

    @staticmethod
    def aggregate_zone_risk(assessments: list[HazardAssessment]) -> dict:
        """
        Summarize risk for an entire zone from all worker assessments.
        Returns zone-level stats for the dashboard.
        """
        if not assessments:
            return {"zone_risk_score": 0, "zone_risk_level": "normal", "active_alerts": []}

        max_score = max(a.hazard_score for a in assessments)
        active_alerts = [a.primary_alert for a in assessments if a.hazard_score >= 40]
        fall_events = [a for a in assessments if a.fall_detected]
        ppe_violations = [a for a in assessments if not a.ppe_compliant]

        if max_score >= 90:
            zone_risk_level = "critical"
        elif max_score >= 70:
            zone_risk_level = "high"
        elif max_score >= 40:
            zone_risk_level = "elevated"
        else:
            zone_risk_level = "normal"

        return {
            "zone_risk_score": max_score,
            "zone_risk_level": zone_risk_level,
            "worker_count": len(assessments),
            "fall_events": len(fall_events),
            "ppe_violations": len(ppe_violations),
            "active_alerts": active_alerts,
        }
