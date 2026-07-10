from fastapi import APIRouter, File, UploadFile, Form
import base64
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.voice.transcriber import VoiceAgent
from agents.memory.retriever import MemoryRetriever, MemoryRequest

router = APIRouter(tags=["Voice Interaction"])

from pydantic import BaseModel

class VoiceQueryJSON(BaseModel):
    audio_base64: str
    project_id: str = "P-001"
    zone_id: str = "A12"
    worker_id: str = "W-001"

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

@router.post("/query_json")
async def voice_query_json(req: VoiceQueryJSON):
    voice_agent = VoiceAgent()
    audio_bytes = base64.b64decode(req.audio_base64)
    
    try:
        transcription = await voice_agent.transcribe(audio_bytes, "voice_query.m4a")
    except Exception as e:
        print(f"Transcription failed: {e}")
        transcription = {"text": "I could not hear that.", "language": "en"}
        
    retriever = MemoryRetriever()
    mem_req = MemoryRequest(
        query=transcription["text"],
        project_id=req.project_id,
        zone_id=req.zone_id,
        worker_id=req.worker_id
    )
    
    try:
        rag_result = await retriever.answer_query(mem_req)
    except Exception as e:
        print(f"Memory failed: {e}")
        rag_result = {"answer": "I'm sorry, I cannot access the memory right now.", "evidence": []}
        
    try:
        audio_response = await voice_agent.text_to_speech(
            text=rag_result["answer"],
            language=transcription.get("language", "en")
        )
        audio_base64 = base64.b64encode(audio_response).decode()
    except Exception as e:
        print(f"TTS failed: {e}")
        audio_base64 = ""
        
    return {
        "transcript": transcription["text"],
        "detected_language": transcription.get("language", "en"),
        "response_text": rag_result["answer"],
        "audio_base64": audio_base64,
        "evidence": rag_result["evidence"],
        "processing_time_ms": 0
    }
