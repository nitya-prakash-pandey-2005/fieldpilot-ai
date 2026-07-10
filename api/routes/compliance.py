from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
import sys
import os
import asyncpg

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.compliance.validator import ComplianceEngine, ValidationRequest

router = APIRouter(prefix="/api/v1/compliance", tags=["Compliance Validation (Agent 5)"])

# Initialize engine
engine = ComplianceEngine()

class ComplianceRequest(BaseModel):
    zone_id: str
    drawing_id: str
    observed_measurements: List[dict]

@router.post("/validate")
async def validate_measurement(req: ValidationRequest):
    """
    Accepts physical measurements and compares them against specifications.
    Returns PASS/FAIL and required downstream actions.
    """
    try:
        result = await engine.validate(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/issues")
async def get_active_issues():
    uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
    try:
        conn = await asyncpg.connect(uri)
        rows = await conn.fetch("""
            SELECT id, zone_id, asset_type, severity, measured_value, spec_value, deviation_pct, worker_id, status, created_at 
            FROM compliance_events 
            ORDER BY created_at DESC 
            LIMIT 20
        """)
        await conn.close()
        
        # Convert datetime objects to ISO strings for JSON serialization
        return [{**dict(r), "created_at": r["created_at"].isoformat()} for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
