from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid
import sys
import os
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.vision.detector import VisionPipeline
from agents.vision.vlm_analyzer import VLMAnalyzer
# from agents.learning.learning_agent import LearningAgent
# from agents.notification.notification_agent import NotificationAgent
from fastapi import Body

router = APIRouter(prefix="/api/v1/vision", tags=["Vision Agent (Agent 1)"])

# Initialize vision pipeline and VLM
pipeline = VisionPipeline()
vlm_analyzer = VLMAnalyzer()
# learning_agent = LearningAgent()
# notification_agent = NotificationAgent()

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

@router.post("/understand")
async def understand_scene(
    image: str = Body(..., description="Base64 encoded image"),
    zone_id: str = Body("A12"),
    language: str = Body("en"),
    worker_query: str = Body(None),
    project_id: str = Body("P-001")
):
    """
    Main endpoint for glasses stream.
    Combines YOLO detection + VLM understanding.
    Returns spoken response for worker.
    """
    # 1. VLM Scene Understanding
    vlm_result = await vlm_analyzer.analyze_scene(
        image_base64=image,
        zone_id=zone_id,
        language=language,
        worker_query=worker_query,
        project_context=f"Project {project_id} - Zone {zone_id}"
    )
    
    # 2. YOLO Detections (run on temp file)
    temp_dir = os.path.join(os.path.dirname(__file__), "temp_vision")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.jpg")
    
    yolo_result = {"assets_detected": [], "compliance_checks": []}
    try:
        import base64 as b64
        with open(temp_path, "wb") as f:
            img_data = image.split(",")[-1] if "," in image else image
            f.write(b64.b64decode(img_data))
        yolo_result = pipeline.analyze_frame(temp_path)
    except Exception as e:
        print(f"YOLO error in understand endpoint: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    # 3. Log to learning agent
    try:
        # learning_agent.log_observation(
        #     zone_id=zone_id,
        #     observations=yolo_result.get("assets_detected", []),
        #     vlm_analysis=vlm_result,
        #     project_id=project_id
        # )
        pass
    except Exception as e:
        print(f"Error logging to learning agent: {e}")

    # 4. Notify if critical
    urgency = vlm_result.get("urgency", "low").lower()
    if urgency in ["high", "critical"] or vlm_result.get("engineer_alert_needed"):
        try:
            alert_msg = f"VLM Alert in Zone {zone_id}: {vlm_result.get('scene_description')} - {', '.join(vlm_result.get('safety_hazards', []))}"
            # notification_agent.dispatch_alert({
            #     "type": "safety_violation",
            #     "message": alert_msg,
            #     "severity": urgency.upper(),
            #     "zone_id": zone_id
            # })
            pass
        except Exception as e:
            print(f"Error sending notification: {e}")

    # Return unified payload
    return {
        "scene": vlm_result,
        "detections": yolo_result,
        "spoken_response": vlm_result.get("spoken_response", ""),
        "language": language
    }
