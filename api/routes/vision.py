from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid
import sys
import os
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.vision.detector import VisionPipeline

router = APIRouter(prefix="/api/v1/vision", tags=["Vision Agent (Agent 1)"])

# Initialize vision pipeline
pipeline = VisionPipeline()

@router.post("/analyze")
async def analyze_image(file: UploadFile = File(...)):
    """
    Accepts an image and triggers the Vision Agent to detect elements, PPE, and structural components.
    In MVP, this directly calls the pipeline for immediate response. In production, this queues a job.
    """
    job_id = str(uuid.uuid4())
    
    # Save uploaded file to temp directory
    temp_dir = os.path.join(os.path.dirname(__file__), "temp_vision")
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)
    
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Run vision inference
        results = pipeline.analyze_frame(temp_file_path)
        
        return {
            "status": "completed",
            "job_id": job_id,
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@router.get("/status/{job_id}")
async def get_vision_status(job_id: str):
    # Mock status retrieval
    return {
        "job_id": job_id,
        "status": "completed",
        "detections": [
            {"label": "Hardhat", "confidence": 0.98, "bbox": [100, 150, 200, 250]},
            {"label": "Rebar", "confidence": 0.95, "bbox": [300, 400, 500, 600]}
        ]
    }
