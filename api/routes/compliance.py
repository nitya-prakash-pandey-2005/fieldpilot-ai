from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.compliance.validator import ComplianceEngine, ValidationRequest
from db import get_db
from models.compliance import ComplianceEvent
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
async def get_active_issues(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(ComplianceEvent).order_by(ComplianceEvent.created_at.desc()).limit(20)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "zone_code": r.zone_code,
                "asset_id": r.asset_id,
                "field_issue_id": r.field_issue_id,
                "severity": r.severity,
                "measured_value": r.measured_value,
                "spec_value": r.spec_value,
                "deviation_pct": r.deviation_pct,
                "confidence": r.confidence,
                "worker_id": r.worker_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
