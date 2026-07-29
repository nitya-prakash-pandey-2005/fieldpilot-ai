from fastapi import APIRouter, File, UploadFile, Form
from pydantic import BaseModel
# from agents.voice.voice_agent import VoiceAgent
from agents.memory.retriever import QdrantRetrieval
from agents.voice.tts import synthesize_speech
import base64
import tempfile
from groq import Groq
import os

router = APIRouter(prefix="/api/v1/voice", tags=["Voice Agent (Agent 11)"])
# voice_agent = VoiceAgent()
retriever = QdrantRetrieval()

# Ensure we have a GROQ client
api_key = os.getenv("GROQ_API_KEY")
llm_client = Groq(api_key=api_key) if api_key else None

@router.post("/query")
async def voice_query(
    audio: UploadFile = File(...),
    project_id: str = Form("P-001"),
    zone_id: str = Form("A12")
):
    audio_bytes = await audio.read()

    # Save audio temporarily for Groq API. Uses a unique tempfile (not a
    # fixed "temp_audio_query.wav" in the CWD) so concurrent requests don't
    # clobber each other's audio mid-transcription.
    fd, temp_audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with open(temp_audio_path, "wb") as f:
        f.write(audio_bytes)
        
    user_query = ""
    lang = "en"
    
    try:
        if llm_client:
            with open(temp_audio_path, "rb") as file:
                transcription = llm_client.audio.transcriptions.create(
                  file=(temp_audio_path, file.read()),
                  model="whisper-large-v3-turbo",
                  response_format="json"
                )
            user_query = transcription.text
            print(f"Transcribed: {user_query}")
    except Exception as e:
        print(f"STT Error: {e}")
        
    if os.path.exists(temp_audio_path):
        os.remove(temp_audio_path)
    
    if not user_query:
        return {"transcript": "Error", "response_text": "Could not understand audio.", "audio_base64": ""}
    
    # RAG lookup via existing Qdrant retriever
    try:
        results = await retriever.search(user_query, project_id, top_k=3)
        context = "\n".join([r.text for r in results])
    except Exception as e:
        print(f"Retrieval error: {e}")
        context = ""
    
    # LLM Answer
    lang_name = "English" if lang == "en" else lang
    
    system_prompt = f"""
    Answer this construction worker's question in {lang_name}.
    Be brief (2-3 sentences max). Be specific. Be helpful.
    
    Context from project documentation:
    {context}
    
    If context doesn't answer it directly, give a safe general construction answer.
    """
    
    answer = "I'm sorry, my language engine is currently offline."
    if llm_client:
        try:
            response = llm_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ]
            )
            answer = response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error: {e}")
    
    audio_b64 = synthesize_speech(answer) or ""  # falls back to client-side TTS if Gemini isn't configured/reachable

    return {
        "transcript": user_query,
        "detected_language": lang,
        "response_text": answer,
        "audio_base64": audio_b64,
    }


class VoiceQueryPayload(BaseModel):
    audio_base64: str
    project_id: str = "P-001"
    zone_id: str = "A12"
    worker_id: str = "W-001"

@router.post("/query_json")
async def voice_query_json(payload: VoiceQueryPayload):
    audio_bytes = base64.b64decode(payload.audio_base64)

    # Unique tempfile — see /query above for why this isn't a fixed filename.
    fd, temp_audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with open(temp_audio_path, "wb") as f:
        f.write(audio_bytes)
        
    user_query = ""
    lang = "en"
    
    try:
        if llm_client:
            with open(temp_audio_path, "rb") as file:
                transcription = llm_client.audio.transcriptions.create(
                  file=(temp_audio_path, file.read()),
                  model="whisper-large-v3-turbo",
                  response_format="json"
                )
            user_query = transcription.text
            print(f"Transcribed: {user_query}")
    except Exception as e:
        print(f"STT Error: {e}")
        
    if os.path.exists(temp_audio_path):
        os.remove(temp_audio_path)
    
    if not user_query:
        return {"transcript": "Error", "response_text": "Could not understand audio.", "audio_base64": ""}
    
    # RAG lookup via existing Qdrant retriever
    try:
        results = await retriever.search(user_query, payload.project_id, top_k=3)
        context = "\n".join([r.text for r in results])
        evidence = [{"text": r.text, "source": r.source} for r in results]
    except Exception as e:
        print(f"Retrieval error: {e}")
        context = ""
        evidence = []
    
    # LLM Answer
    lang_name = "English" if lang == "en" else lang
    
    system_prompt = f"""
    Answer this construction worker's question in {lang_name}.
    Be brief (2-3 sentences max). Be specific. Be helpful.
    
    Context from project documentation:
    {context}
    
    If context doesn't answer it directly, give a safe general construction answer.
    """
    
    answer = "I'm sorry, my language engine is currently offline."
    if llm_client:
        try:
            response = llm_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ]
            )
            answer = response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error: {e}")
    
    audio_b64 = synthesize_speech(answer) or ""  # falls back to client-side TTS if Gemini isn't configured/reachable

    return {
        "transcript": user_query,
        "detected_language": lang,
        "response_text": answer,
        "audio_base64": audio_b64,
        "evidence": evidence
    }
