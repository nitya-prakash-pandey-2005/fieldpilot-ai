from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/planning", tags=["Planning"])

@router.get("/predictions")
async def get_predictions():
    return {
        "status": "success",
        "data": [
            {
                "id": "pred-1",
                "title": "Concrete Delay Risk",
                "description": "High probability of concrete pour delay due to rebar spacing issues in Zone A12.",
                "probability": 0.85,
                "impact": "High",
                "confidence": 0.85,
                "action": "Review",
                "zone": "Zone A12"
            }
        ]
    }
