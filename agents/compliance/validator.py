from datetime import datetime
from pydantic import BaseModel
import uuid
import os
import sys

# Make the api/ package (models.*, db.py) importable regardless of whether
# this module is loaded via uvicorn (api/main.py already puts api/ on
# sys.path) or run standalone — mirrors the sys.path pattern api/routes/*.py
# already uses for the repo root.
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
if _API_DIR not in sys.path:
    sys.path.append(_API_DIR)

class Measurement(BaseModel):
    parameter: str
    measured_value: float
    unit: str
    confidence: float

class Specification(BaseModel):
    spec_id: str
    expected_value: float
    tolerance_min: float
    tolerance_max: float
    unit: str
    standard_ref: str

class ValidationRequest(BaseModel):
    observation_id: str
    asset_id: str
    zone_id: str
    measurement: Measurement
    specification: Specification

class ComplianceEngine:
    async def _write_inspection(self, req: ValidationRequest, result: str, confidence: float):
        # Real Knowledge Graph write — see agents/knowledge_graph/writer.py.
        # Called for every outcome (not just FAIL) so get_zone_risk_score's
        # failures/total ratio in agents/knowledge_graph/queries.py reflects
        # real inspection volume, not just failures.
        try:
            from agents.knowledge_graph.writer import write_inspection
            await write_inspection(
                zone_id=req.zone_id,
                asset_id=req.asset_id,
                result=result,
                confidence=confidence,
                asset_type_hint=req.measurement.parameter,
            )
        except Exception as e:
            print(f"Failed to write Inspection node to Neo4j: {e}")

    async def validate(self, req: ValidationRequest):
        m = req.measurement
        s = req.specification

        # Unit conversion would go here if units mismatched. Assuming matching for MVP.
        measured = m.measured_value
        expected = s.expected_value
        tol_min = s.tolerance_min
        tol_max = s.tolerance_max
        meas_confidence = m.confidence

        # Core validation logic
        if meas_confidence < 0.75:
            await self._write_inspection(req, "UNCERTAIN", meas_confidence)
            return self._build_response(req, "UNCERTAIN", meas_confidence, "LOW")

        if tol_min <= measured <= tol_max:
            await self._write_inspection(req, "PASS", meas_confidence)
            return self._build_response(req, "PASS", meas_confidence, "LOW")

        # Calculation deviation
        absolute_dev = abs(measured - expected)
        deviation_pct = (absolute_dev / expected) * 100
        direction = "over" if measured > expected else "under"
        
        # Severity calculation
        if deviation_pct > 25:
            severity = "CRITICAL"
        elif deviation_pct > 10:
            severity = "HIGH"
        elif deviation_pct > 5:
            severity = "MEDIUM"
        else:
            severity = "LOW"
            
        res = self._build_response(req, "FAIL", meas_confidence, severity, absolute_dev, deviation_pct, direction)
        await self._write_inspection(req, "FAIL", meas_confidence)

        # Write to the SAME unified Postgres DB/ORM as FieldIssue (previously
        # this wrote to a raw-asyncpg `compliance_events` table in a
        # completely separate `askthewall` database — the two "issue"
        # concepts never saw each other). A FAIL now creates a real
        # FieldIssue AND a linked ComplianceEvent in one transaction, then
        # actually dispatches a notification for HIGH/CRITICAL instead of
        # just returning "trigger_notification_agent" in the response and
        # never calling it.
        try:
            from db import async_session
            from models.issues import FieldIssue
            from models.compliance import ComplianceEvent

            async with async_session() as session:
                field_issue = FieldIssue(
                    project_id="default-project",
                    zone_code=req.zone_id,
                    issue_type=f"{m.parameter}_deviation",
                    severity=severity.lower(),
                    description=res["explanation"]["engineer_message"],
                    deviation_pct=round(deviation_pct, 2),
                    measured_value=f"{measured}{m.unit}",
                    expected_value=f"{expected}{s.unit}",
                    detected_by="compliance_agent",
                    drawing_ref=getattr(s, "standard_ref", None),
                )
                session.add(field_issue)
                await session.flush()  # assigns field_issue.id

                compliance_event = ComplianceEvent(
                    zone_code=req.zone_id,
                    asset_id=req.asset_id,
                    field_issue_id=field_issue.id,
                    severity=severity,
                    measured_value=measured,
                    spec_value=expected,
                    deviation_pct=round(deviation_pct, 2),
                    confidence=round(meas_confidence, 3),
                    status="open",
                )
                session.add(compliance_event)
                await session.commit()
                res["field_issue_id"] = field_issue.id

            # Broadcast the event to the live dashboard twin
            try:
                from main import broadcast_event
                await broadcast_event("P-001", {
                    "type": "COMPLIANCE_FAIL",
                    "zone_id": req.zone_id,
                    "asset_id": req.asset_id,
                    "severity": severity,
                    "deviation_pct": deviation_pct,
                    "field_issue_id": field_issue.id,
                })
            except Exception as e:
                print(f"Failed to broadcast compliance event: {e}")

            # Actually dispatch the notification for HIGH/CRITICAL instead
            # of only listing it under downstream_actions.
            if severity in ("HIGH", "CRITICAL"):
                from agents.notification.router import NotificationRouter, NotificationEvent
                notifier = NotificationRouter()
                await notifier.dispatch(NotificationEvent(
                    notification_id=str(uuid.uuid4()),
                    event_type="COMPLIANCE_FAIL",
                    severity=severity,
                    zone_id=req.zone_id,
                    asset_id=req.asset_id,
                    message=res["explanation"]["engineer_message"],
                    evidence={"field_issue_id": field_issue.id},
                    routing={},
                ))

                # Cross-worker hazard advisory — only OTHER sessions
                # subscribed to this SAME zone's WebSocket channel receive
                # it (a worker in a different zone gets nothing), unlike
                # the project-wide broadcast_event above.
                try:
                    from main import broadcast_zone_advisory
                    await broadcast_zone_advisory(req.zone_id, {
                        "type": "ZONE_HAZARD_ADVISORY",
                        "zone_id": req.zone_id,
                        "asset_id": req.asset_id,
                        "severity": severity,
                        "message": res["explanation"]["worker_message"],
                        "field_issue_id": field_issue.id,
                        "timestamp": res["timestamp"],
                    })
                except Exception as e:
                    print(f"Failed to broadcast zone advisory: {e}")

        except Exception as e:
            print(f"Failed to persist/dispatch compliance event: {e}")

        return res
        
    def _build_response(self, req, result, confidence, severity, abs_dev=0.0, pct_dev=0.0, direction="none"):
        m = req.measurement
        s = req.specification
        
        if result == "PASS":
            worker_msg = f"{m.parameter.capitalize()} is {m.measured_value}{m.unit}, which is within specification ({s.tolerance_min}-{s.tolerance_max}{s.unit}). Good to go."
            eng_msg = f"Zone {req.zone_id}, Asset {req.asset_id}: {m.parameter.capitalize()} {m.measured_value}{m.unit} passed per {s.standard_ref}."
            audio_msg = "PASS. Measurement is within tolerance."
            actions = []
        elif result == "UNCERTAIN":
            worker_msg = f"Measurement confidence too low ({confidence*100:.1f}%). Please rescan."
            eng_msg = f"Zone {req.zone_id}, Asset {req.asset_id}: Measurement scan failed confidence threshold."
            audio_msg = "UNCERTAIN. Please rescan the area."
            actions = []
        else:
            stop_str = " STOP WORK." if severity in ["HIGH", "CRITICAL"] else ""
            worker_msg = f"{m.parameter.capitalize()} is {m.measured_value}{m.unit}. Specification requires {s.expected_value}{s.unit} ({s.tolerance_min}-{s.tolerance_max}). Deviation is {abs_dev:.1f}{s.unit} {direction} maximum.{stop_str}"
            eng_msg = f"Zone {req.zone_id}, Asset {req.asset_id}: Measured {m.parameter} {m.measured_value}{m.unit} exceeds tolerance ({s.tolerance_min}-{s.tolerance_max}{s.unit}) per {s.standard_ref}. Deviation: {pct_dev:.1f}%."
            audio_msg = f"FAIL. {m.parameter.capitalize()} exceeds tolerance by {abs_dev:.1f} {s.unit}. {stop_str}"
            actions = ["trigger_notification_agent"]
            if severity in ["HIGH", "CRITICAL"]:
                actions.append("trigger_predictive_rfi_agent")
                
        return {
            "validation_id": str(uuid.uuid4()),
            "result": result,
            "confidence": confidence,
            "deviation": {
                "absolute": round(abs_dev, 2),
                "percentage": round(pct_dev, 2),
                "direction": direction
            },
            "severity": severity,
            "explanation": {
                "worker_message": worker_msg,
                "engineer_message": eng_msg,
                "glasses_audio": audio_msg
            },
            "downstream_actions": actions,
            "timestamp": datetime.utcnow().isoformat()
        }
