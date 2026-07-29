import sys
import os
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.predictive_rfi.predictor import RFIPredictor, RFIRequest, CurrentActivity

from db import get_db
from models.zones import Zone

router = APIRouter(prefix="/api/v1/planning", tags=["Planning"])

predictor = RFIPredictor()


def _impact_from_probability(p: float) -> str:
    if p >= 0.75:
        return "High"
    if p >= 0.5:
        return "Medium"
    return "Low"


@router.get("/predictions")
async def get_predictions(project_id: str = "default-project", db: AsyncSession = Depends(get_db)):
    """
    Real cross-zone aggregate for the home page's compact PredictedRFIPanel —
    previously a single hardcoded prediction returned regardless of project
    state. Calls the same RFIPredictor.predict() used by POST /api/v1/rfi/predict
    (real Neo4j historical-RFI query + real Qdrant similarity search + LLM
    synthesis) once per zone, then flattens to the panel's compact shape.
    Returns [] rather than fabricated data if there are no zones yet or all
    predictions fail — the panel's own fallback demo data covers that case.
    """
    result = await db.execute(select(Zone).where(Zone.project_id == project_id))
    zones = result.scalars().all()

    predictions = []
    for zone in zones:
        try:
            req = RFIRequest(
                project_id=project_id,
                zone_id=zone.zone_code,
                current_activity=CurrentActivity(
                    work_type=zone.current_activity or "general construction",
                    drawing_refs=[],
                    scheduled_completion="",
                ),
            )
            prediction = await predictor.predict(req)
        except Exception:
            continue

        for p in prediction.get("predicted_rfis", []):
            predictions.append({
                "id": p.get("prediction_id") or f"pred-{zone.zone_code}-{len(predictions)}",
                "title": (p.get("rfi_category") or "Predicted RFI").replace("_", " ").title(),
                "confidence": p.get("probability", prediction.get("confidence", 0.5)),
                "impact": _impact_from_probability(p.get("probability", 0.5)),
                "action": "Draft RFI",
                "zone": f"Zone {zone.zone_code}",
            })

    predictions.sort(key=lambda p: p["confidence"], reverse=True)

    return {"status": "success", "data": predictions[:10]}
