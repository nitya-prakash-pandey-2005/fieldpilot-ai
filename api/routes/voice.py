"""
Voice Agent — speech in, cited answer + spoken reply out.

Both endpoints share one implementation. They were previously two near-identical
copies that had already drifted: /query returned no `evidence` while
/query_json did, so a client's answer came with citations or without depending
purely on which upload format it happened to use.

  POST /query       multipart audio upload — what the mobile app uses. Avoids
                    base64's 33% payload inflation over site WiFi, and lets the
                    phone stream a file URI straight into FormData with no
                    filesystem library involved.
  POST /query_json  base64 in JSON — kept for the web dashboard and for the
                    offline queue, which stores captures as base64.
"""

import base64
import os
import sys
import tempfile
import time

from fastapi import APIRouter, File, Form, UploadFile
from groq import Groq
from pydantic import BaseModel

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from agents.memory.retriever import QdrantRetrieval
from agents.voice.tts import synthesize_speech
from routes.interactions import record_interaction

router = APIRouter(prefix="/api/v1/voice", tags=["Voice Agent (Agent 11)"])
retriever = QdrantRetrieval()

api_key = os.getenv("GROQ_API_KEY")
llm_client = Groq(api_key=api_key) if api_key else None

STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
VOICE_LLM_MODEL = os.getenv("VOICE_LLM_MODEL", "llama-3.1-8b-instant")
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _transcribe(audio_bytes: bytes, suffix: str = ".wav") -> str:
    if not llm_client:
        return ""
    # Unique tempfile, not a fixed name in the CWD: concurrent workers would
    # otherwise clobber each other's audio mid-transcription.
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(audio_bytes)
        with open(path, "rb") as f:
            transcription = llm_client.audio.transcriptions.create(
                file=(path, f.read()), model=STT_MODEL, response_format="json")
        return (transcription.text or "").strip()
    except Exception as e:
        print(f"[VOICE] STT error: {e}")
        return ""
    finally:
        if os.path.exists(path):
            os.remove(path)


async def _answer_voice_query(audio_bytes: bytes, project_id: str, zone_id: str,
                              worker_id: str | None, suffix: str = ".wav") -> dict:
    t0 = time.time()

    if not audio_bytes:
        return {"transcript": "", "response_text": "No audio received.",
                "audio_base64": "", "evidence": [], "error": "empty_audio"}
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return {"transcript": "", "response_text": "Recording too long.",
                "audio_base64": "", "evidence": [], "error": "audio_too_large"}

    user_query = _transcribe(audio_bytes, suffix)
    if not user_query:
        reason = ("speech-to-text is not configured (no GROQ_API_KEY)"
                  if not llm_client else "the audio could not be understood")
        return {"transcript": "", "detected_language": "en",
                "response_text": f"Sorry — {reason}. Please try again.",
                "audio_base64": "", "evidence": [], "error": "transcription_failed"}

    # RAG over indexed project documents.
    context, evidence = "", []
    try:
        results = await retriever.search(user_query, project_id, top_k=3)
        context = "\n".join(r.text for r in results)
        evidence = [{"text": r.text, "source": r.source} for r in results]
    except Exception as e:
        print(f"[VOICE] retrieval unavailable: {e}")

    system_prompt = f"""
    Answer this construction worker's question. Be brief (2-3 sentences max),
    specific and actionable — it will be read aloud into their ear while they
    are working.

    Context from project documentation:
    {context if context else "(no project documents matched this question)"}

    If the context does not answer the question, say so plainly and give a safe
    general construction answer. Never invent a specification value, a drawing
    number, or an approval — if you don't have it, say it needs to be confirmed
    with the site engineer.
    """

    answer = "I'm sorry, my language engine is currently offline."
    if llm_client:
        try:
            response = llm_client.chat.completions.create(
                model=VOICE_LLM_MODEL,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_query}])
            answer = response.choices[0].message.content
        except Exception as e:
            print(f"[VOICE] LLM error: {e}")

    # Falls back to client-side TTS if Gemini isn't configured/reachable.
    audio_b64 = synthesize_speech(answer) or ""

    await record_interaction(
        kind="voice", worker_id=worker_id, zone_code=zone_id, project_id=project_id,
        query=user_query, result=answer,
        agent_chain="A11:Voice -> A7:Memory(RAG)" + (" -> TTS" if audio_b64 else ""),
        latency_ms=round((time.time() - t0) * 1000, 1),
    )

    return {
        "transcript": user_query,
        "detected_language": "en",
        "response_text": answer,
        "audio_base64": audio_b64,
        "evidence": evidence,
    }


@router.post("/query")
async def voice_query(
    audio: UploadFile = File(...),
    project_id: str = Form("P-001"),
    zone_id: str = Form("A12"),
    worker_id: str = Form(None),
):
    """Multipart upload — the mobile path."""
    suffix = os.path.splitext(audio.filename or "")[1] or ".wav"
    return await _answer_voice_query(await audio.read(), project_id, zone_id,
                                     worker_id, suffix)


class VoiceQueryPayload(BaseModel):
    audio_base64: str
    project_id: str = "P-001"
    zone_id: str = "A12"
    worker_id: str = "W-001"


@router.post("/query_json")
async def voice_query_json(payload: VoiceQueryPayload):
    """Base64-in-JSON — the web dashboard and offline-queue path."""
    try:
        raw = payload.audio_base64.split(",", 1)[-1] if "," in payload.audio_base64 \
            else payload.audio_base64
        audio_bytes = base64.b64decode(raw)
    except Exception as e:
        return {"transcript": "", "response_text": "Malformed audio payload.",
                "audio_base64": "", "evidence": [], "error": f"decode_failed: {e}"}

    return await _answer_voice_query(audio_bytes, payload.project_id,
                                     payload.zone_id, payload.worker_id)


@router.get("/status")
async def voice_status():
    """Which half of the voice pipeline is actually live, so the UI can say
    'speech-to-text unavailable' instead of silently failing to hear anything."""
    return {
        "stt": {"configured": bool(llm_client), "model": STT_MODEL,
                "provider": "groq"},
        "llm": {"configured": bool(llm_client), "model": VOICE_LLM_MODEL},
        "tts": {"configured": bool(os.getenv("GEMINI_API_KEY")),
                "provider": "gemini",
                "note": "falls back to client-side TTS when unset"},
    }
