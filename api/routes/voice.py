from fastapi import APIRouter, File, UploadFile, Form
import base64
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.voice.transcriber import VoiceAgent
from agents.memory.retriever import MemoryRetriever, MemoryRequest

router = APIRouter(tags=["Voice Interaction"])

@router.post("/query")
async def voice_query(
    audio: UploadFile = File(...),
    project_id: str = Form("P-001"),
    zone_id: str = Form("A12"),
    worker_id: str = Form("W-001")
):
    voice_agent = VoiceAgent()
    
    # Step 1: Transcribe
    audio_bytes = await audio.read()
    transcription = await voice_agent.transcribe(
        audio_bytes, audio.filename
    )
    
    # Step 2: Query Agent 7 Memory
    retriever = MemoryRetriever()
    
    req = MemoryRequest(
        query=transcription["text"],
        project_id=project_id,
        zone_id=zone_id,
        worker_id=worker_id
    )
    
    rag_result = await retriever.answer_query(req)
    
    # Step 3: Generate TTS response
    audio_response = await voice_agent.text_to_speech(
        text=rag_result["answer"],
        language=transcription["language"]
    )
    
    audio_base64 = base64.b64encode(
        audio_response
    ).decode()
    
    return {
        "transcript": transcription["text"],
        "detected_language": transcription["language"],
        "response_text": rag_result["answer"],
        "audio_base64": audio_base64,
        "evidence": rag_result["evidence"],
        "processing_time_ms": 0
    }
