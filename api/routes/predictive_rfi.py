from fastapi import APIRouter, HTTPException
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.predictive_rfi.predictor import RFIPredictor, RFIRequest

router = APIRouter(prefix="/api/v1/rfi", tags=["Predictive RFI (Agent 6)"])

# Initialize predictor
predictor = RFIPredictor()

@router.post("/predict")
async def predict_rfis(req: RFIRequest):
    """
    Analyzes current zone activity against historical data and predicts potential RFIs.
    """
    try:
        result = await predictor.predict(req)
        return {
            "status": "success",
            "prediction": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
