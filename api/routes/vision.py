from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid
import sys
import os
import shutil
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.vision.detector import VisionPipeline
from agents.vision.vlm_analyzer import VLMAnalyzer
from routes.interactions import record_interaction
# from agents.learning.learning_agent import LearningAgent
# from agents.notification.notification_agent import NotificationAgent
from fastapi import Body

router = APIRouter(prefix="/api/v1/vision", tags=["Vision Agent (Agent 1)"])


def _json_safe(obj):
    """
    Recursively strip/convert values VisionPipeline.analyze_frame() returns
    that FastAPI's jsonable_encoder can't serialize: the raw annotated_frame
    ndarray (meant for local display/streaming, e.g. live_feed.py's base64
    JPEG encoding — never meant to ride in a JSON body) is dropped entirely,
    and any stray numpy scalars (np.float32 etc., which round()/float() on
    a numpy type doesn't always fully convert) are cast to native Python
    types. Without this, /understand and /analyze 500 on every real call.
    """
    if isinstance(obj, np.ndarray):
        return None
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items() if k != "annotated_frame"}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj

# Initialize vision pipeline and VLM
pipeline = VisionPipeline()
vlm_analyzer = VLMAnalyzer()
# learning_agent = LearningAgent()
# notification_agent = NotificationAgent()

@router.get("/brain/status")
async def brain_status():
    """Which scene-reasoning backend is live, and if Gemma is selected, whether
    its weights actually loaded. Reports without forcing an 8B load."""
    from agents.vision.gemma_analyzer import GemmaAnalyzer
    from agents.vision.vlm_analyzer import VLM_BACKEND

    payload = {"backend": VLM_BACKEND}
    if VLM_BACKEND == "gemma":
        payload["gemma"] = GemmaAnalyzer.instance().status()
    return payload


@router.post("/identify")
async def identify_objects(
    image: str = Body(..., embed=True, description="Base64 encoded image"),
    hint: str = Body("", embed=True, description="Optional focus, e.g. 'structural elements'"),
):
    """Open-vocabulary object identification — Gemma 4 as the brain.

    Distinct from /analyze, which is YOLO's fixed class list. This names things
    no detector in the repo has a class for (rebar cage, formwork, cable tray).
    Returns 503 with the specific reason when the model is not loaded, rather
    than an empty list that would read as "nothing in the frame".
    """
    from fastapi import HTTPException as _HTTPException

    result = await vlm_analyzer.identify_objects(image, hint)
    if result.get("status") != "ok":
        raise _HTTPException(status_code=503, detail=result)
    return _json_safe(result)


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
            "results": _json_safe(results)
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
    project_id: str = Body("P-001"),
    worker_id: str = Body(None),
):
    """
    Main endpoint for glasses stream.
    Combines YOLO detection + VLM understanding.
    Returns spoken response for worker.
    """
    import time as _time
    _t0 = _time.time()

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

    # 5. Append to the worker's interaction history / audit trail. Best-effort:
    # record_interaction never raises, so a history failure cannot turn a
    # successful scan into a failed request.
    hazards = vlm_result.get("safety_hazards") or []
    issues = vlm_result.get("compliance_issues") or []
    await record_interaction(
        kind="voice" if worker_query else "scan",
        worker_id=worker_id,
        zone_code=zone_id,
        project_id=project_id,
        query=worker_query or (vlm_result.get("work_type") or "Scene scan"),
        result=(vlm_result.get("spoken_response")
                or vlm_result.get("scene_description") or "")[:4000],
        # Only a compliance check produces a PASS/FAIL. A scene description is
        # informational, and labelling it PASS would imply an inspection that
        # never happened.
        verdict=("FAIL" if (urgency in ("high", "critical") or issues)
                 else "INFO"),
        severity=urgency.upper() if urgency else None,
        confidence=(vlm_result.get("confidence")
                    if isinstance(vlm_result.get("confidence"), (int, float)) else None),
        agent_chain="A1:Vision -> VLM" + (" -> A9:Notify" if hazards or issues else ""),
        latency_ms=round((_time.time() - _t0) * 1000, 1),
    )

    # Return unified payload
    return _json_safe({
        "scene": vlm_result,
        "detections": yolo_result,
        "spoken_response": vlm_result.get("spoken_response", ""),
        "language": language
    })
