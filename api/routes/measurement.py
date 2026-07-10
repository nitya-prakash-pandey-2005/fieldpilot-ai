from fastapi import APIRouter, UploadFile, File, Form, HTTPException
import uuid
import sys
import os
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.measurement.estimator import MeasurementEngine

router = APIRouter(prefix="/api/v1/measurement", tags=["Measurement Agent (Agent 2)"])

# Initialize engine
engine = MeasurementEngine()

@router.post("/measure")
async def measure_elements(
    file: UploadFile = File(...),
    reference_length_mm: float = Form(None),
    measurement_type: str = Form("length")
):
    """
    Accepts an image and optionally a reference length. Triggers Measurement Agent to estimate metrics.
    In MVP, this directly calls the engine for immediate response.
    """
    job_id = str(uuid.uuid4())
    
    # Save uploaded file to temp directory
    temp_dir = os.path.join(os.path.dirname(__file__), "temp_measurement")
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)
    
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Run metric estimation
        results = engine.estimate_measurements(temp_file_path, reference_length_mm)
        
        return {
            "status": "completed",
            "job_id": job_id,
            "measurement_type": measurement_type,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@router.get("/status/{job_id}")
async def get_measurement_status(job_id: str):
    # Mock status retrieval
    return {
        "job_id": job_id,
        "status": "completed",
        "measurements": [
            {"element": "Rebar spacing", "estimated_value": 14.5, "unit": "inches", "confidence": 0.88}
        ]
    }
