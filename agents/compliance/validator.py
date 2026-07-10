from datetime import datetime
from pydantic import BaseModel
import uuid
import asyncpg
import os

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
            return self._build_response(req, "UNCERTAIN", meas_confidence, "LOW")
            
        if tol_min <= measured <= tol_max:
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
        
        # Insert into compliance_events
        uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
        try:
            conn = await asyncpg.connect(uri)
            await conn.execute('''
            INSERT INTO compliance_events (
                zone_id, asset_type, severity, measured_value, spec_value, deviation_pct
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ''', req.zone_id, req.asset_id, severity, measured, expected, deviation_pct)
            await conn.close()
            
            # Broadcast the event
            from main import broadcast_event
            await broadcast_event("P-001", {
                "type": "COMPLIANCE_FAIL",
                "zone_id": req.zone_id,
                "asset_id": req.asset_id,
                "severity": severity,
                "deviation_pct": deviation_pct
            })
            
        except Exception as e:
            print(f"Failed to insert compliance event: {e}")
            
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
