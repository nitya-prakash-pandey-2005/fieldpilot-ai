"""
Worker device API — the phone standing in for the glasses.

The phone is camera, microphone and speaker at once, and it has to do two very
different jobs at the same time. They are separate endpoints because they run at
completely different rates, and conflating them is what makes this kind of demo
fall over:

  POST /api/v1/worker/watch   the SAFETY loop.  Every ~3s. Must finish in under
                              a second, so it runs the on-device ONNX detector
                              and geometric hazard rules only. Speaks only when
                              the hazard picture CHANGES.

  POST /api/v1/worker/ask     the QUESTION loop. On demand, when the worker asks
                              something. Slower is acceptable here because a
                              person is waiting for an answer and knows they
                              just asked for one.

WHY NOT RUN THE FULL GRAPH CONTINUOUSLY. A cloud orchestrator pass is ~22s on
this hardware. At one frame every three seconds the queue grows without bound
and the worker is warned about a hazard from two minutes ago. The safety loop is
therefore deliberately dumb and fast, and only the question loop reasons.

WHY THE SERVER DEBOUNCES. If the client spoke on every `watch` response with a
hazard in it, a worker standing still next to an open edge would be told about
it every three seconds until they moved. The hazard picture is fingerprinted per
worker and `speak` is only true when that fingerprint changes, so the alert
fires on the transition and then goes quiet. `/watch` also re-arms after
HAZARD_REPEAT_S so a genuine standing danger is not announced exactly once and
then forgotten.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

router = APIRouter(prefix="/api/v1/worker", tags=["Worker Device (phone-as-glasses)"])

# How long before a still-present hazard is announced again.
HAZARD_REPEAT_S = float(os.getenv("HAZARD_REPEAT_S", "45"))

# worker_id -> {"sig": str, "spoken_at": float}
_last_hazard: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WatchRequest(BaseModel):
    frame_b64: str
    worker_id: str = "W-001"
    zone_id: str = "A12"
    speak: bool = Field(True, description="synthesise audio for a new hazard")
    mode: str = Field("edge", description="'edge' keeps it fast; 'cloud' uses the full detector")


class AskRequest(BaseModel):
    audio_b64: Optional[str] = None
    audio_filename: str = "audio.webm"
    text: Optional[str] = Field(None, description="typed question, when there is no microphone")
    frame_b64: Optional[str] = None
    worker_id: str = "W-001"
    zone_id: str = "A12"
    project_id: str = "default-project"
    language: str = "en"
    mode: str = "cloud"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode(frame_b64: str) -> np.ndarray:
    import cv2
    b64 = frame_b64.split(",", 1)[-1]
    img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise HTTPException(400, detail="frame did not decode as an image")
    return img


def _speakable(passage: str, limit: int = 260) -> str:
    """Trim a retrieved passage to something a person can actually listen to.

    Two problems with reading a raw chunk aloud. It starts mid-word — PDF
    chunking cuts wherever the token budget ran out, so the worker hears
    "ow what kind of fall protection..." and has no idea they missed anything.
    And it runs long: Kokoro spends about ten seconds synthesising 400
    characters, which is ten seconds of a worker standing still holding a tool.

    So: start at the first sentence boundary, end at the last one inside the
    limit. Truncation is marked rather than silent — a sentence that stops dead
    sounds like the system crashed mid-answer.
    """
    text = " ".join((passage or "").split())
    if not text:
        return ""

    # Drop a leading partial sentence, but only if doing so leaves something.
    for i, ch in enumerate(text[:160]):
        if ch in ".!?" and i + 2 < len(text):
            candidate = text[i + 1:].lstrip()
            if len(candidate) > 60:
                text = candidate
            break
    else:
        # No boundary found: at least start on a whole word.
        if text[:1].islower() and " " in text[:40]:
            text = text.split(" ", 1)[1]

    if len(text) <= limit:
        return text

    cut = text[:limit]
    stop = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if stop > limit * 0.5:
        return cut[:stop + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def _speak(text: str, mode: str) -> tuple[Optional[str], Optional[str]]:
    from agents.voice import tts as tts_mod
    try:
        return tts_mod.synthesize(text, mode)
    except Exception as e:
        print(f"[worker] TTS failed: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------
#
# Deliberately keyword-based and deterministic rather than an LLM classifier.
# Three reasons: it costs nothing and adds no latency to a path a person is
# waiting on; it is explainable, so a wrong route is debuggable instead of
# mysterious; and a misrouted question here is expensive — sending "is this
# spacing right?" down the chat path would answer from documents without ever
# measuring anything, and sound perfectly confident doing it.
#
# The chosen intent is returned in the response so the UI can show it.

_MEASURE_WORDS = ("spacing", "measure", "measurement", "gap", "distance", "how far",
                  "how wide", "tolerance", "is this right", "is this correct",
                  "check this", "within spec", "off spec", "diameter", "clearance")
_DESCRIBE_WORDS = ("what is in front", "what's in front", "what do you see",
                   "what am i looking at", "describe", "what is this", "what's this",
                   "look at this", "what is happening", "anything unsafe", "is it safe")
_KNOWLEDGE_WORDS = ("what should i do", "next step", "procedure", "spec", "specification",
                    "code", "standard", "osha", "drawing", "rfi", "document", "docs",
                    "search", "requirement", "regulation", "allowed", "permitted")


def classify(question: str) -> str:
    q = (question or "").lower()
    # Measurement first: "is this spacing right, check the doc" is a measurement
    # question that also wants a citation, not a document lookup that happens to
    # mention spacing.
    if any(w in q for w in _MEASURE_WORDS):
        return "measure"
    if any(w in q for w in _DESCRIBE_WORDS):
        return "describe"
    if any(w in q for w in _KNOWLEDGE_WORDS):
        return "knowledge"
    return "knowledge"          # stated default: look it up rather than guess


# ---------------------------------------------------------------------------
# The safety loop
# ---------------------------------------------------------------------------

@router.post("/watch")
async def watch(req: WatchRequest):
    """One frame from the worker's camera, checked for immediate danger."""
    import asyncio

    t0 = time.perf_counter()
    image = _decode(req.frame_b64)

    hazards: list[dict] = []
    backend = "none"
    person_count = 0

    if req.mode == "edge":
        from agents.edge.runtime import get_detector
        det = get_detector()
        if not det.ready:
            return {
                "status": "unavailable",
                "reason": det.load_error or "edge model not loaded",
                "remedy": "export the INT8 model, or call /watch with mode=cloud",
                "hazards": [], "speak": False,
            }
        result = await asyncio.to_thread(det.detect, image)
        payload = result.as_dict()
        hazards = payload.get("hazards", []) or []
        person_count = payload.get("person_count", 0)
        backend = f"onnx:{payload.get('model')}@{payload.get('provider')}"
    else:
        from agents.vision.detector import VisionPipeline
        global _cloud_pipeline
        try:
            _cloud_pipeline
        except NameError:
            _cloud_pipeline = None
        if _cloud_pipeline is None:
            _cloud_pipeline = VisionPipeline()
        result = await asyncio.to_thread(_cloud_pipeline.analyze_ndarray, image)
        checks = result.get("compliance_checks", []) or []
        violations = [c for c in checks if c.get("ppe_score", 1.0) < 1.0]
        falls = result.get("fall_events", []) or []
        struck = result.get("struck_by_events", []) or []
        person_count = len(violations) or (result.get("zone_summary", {}) or {}).get("worker_count", 0)
        hazards = (
            [{"type": "ppe_violation", "detail": c.get("worker_id") or c.get("asset_id")} for c in violations]
            + [{"type": "fall", "detail": w} for w in falls]
            + [{"type": "struck_by", "detail": w} for w in struck]
        )
        backend = "yolo11n+ppe+pose (torch)"

    # Fingerprint the hazard picture, not the frame. Two consecutive frames of
    # the same worker missing the same hard hat must not be two alerts.
    signature = "|".join(sorted(str(h.get("type", "")) for h in hazards))
    prev = _last_hazard.get(req.worker_id, {})
    changed = signature != prev.get("sig", "")
    stale = (time.time() - prev.get("spoken_at", 0)) > HAZARD_REPEAT_S
    should_speak = bool(hazards) and (changed or stale)

    spoken_text, audio_b64, tts_backend = None, None, None
    if should_speak:
        kinds = sorted({str(h.get("type", "hazard")).replace("_", " ") for h in hazards})
        spoken_text = "Safety alert. " + ", ".join(kinds) + " detected. Please check your surroundings."
        if req.speak:
            audio_b64, tts_backend = _speak(spoken_text, req.mode)
        _last_hazard[req.worker_id] = {"sig": signature, "spoken_at": time.time()}
    elif signature != prev.get("sig", ""):
        # Picture changed to "clear" — remember it so the next hazard speaks.
        _last_hazard[req.worker_id] = {"sig": signature, "spoken_at": prev.get("spoken_at", 0)}

    return {
        "status": "ok",
        "backend": backend,
        "person_count": person_count,
        "hazards": hazards,
        "hazard_count": len(hazards),
        "speak": should_speak,
        "spoken_text": spoken_text,
        "audio_base64": audio_b64,
        "tts_backend": tts_backend,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# The question loop
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(req: AskRequest):
    """A spoken (or typed) question from the worker, answered out loud.

    Everything the worker hears is grounded in something: a model that looked at
    the frame, a measurement that was actually taken, or a passage that was
    actually retrieved. When none of those produce anything, the answer says so
    rather than filling the silence.
    """
    t0 = time.perf_counter()

    # -- 1. what did they say --------------------------------------------
    transcript, stt_backend = (req.text or "").strip(), "typed"
    stt_attempts: list[dict] = []
    if req.audio_b64 and not transcript:
        import asyncio
        from agents.voice import stt as stt_mod
        raw = base64.b64decode(req.audio_b64.split(",", 1)[-1])
        out = await asyncio.to_thread(stt_mod.transcribe, raw, req.audio_filename)
        transcript, stt_backend, stt_attempts = out.text.strip(), out.backend, out.attempts

    if not transcript:
        # Distinguish "you said nothing" from "every speech backend refused us".
        # Telling a worker to speak up when the real problem is a rejected API
        # key sends them into a loop that cannot succeed.
        failed = [a for a in stt_attempts if a.get("error")]
        if failed:
            return {
                "status": "stt_failed",
                "answer": "Speech recognition is unavailable, so I could not hear that. "
                          "Type your question instead, or check the site server.",
                "transcript": "", "audio_base64": None,
                "stt_attempts": stt_attempts,
            }
        return {"status": "no_speech",
                "answer": "I did not catch that. Hold the button while you speak.",
                "transcript": "", "audio_base64": None}

    intent = classify(transcript)
    answer: str = ""
    citations: list[dict] = []
    measurement: dict | None = None
    compliance: dict | None = None
    detail: dict = {}

    # -- 2. answer it, by intent -----------------------------------------
    if intent == "describe":
        if not req.frame_b64:
            answer = "I need a camera frame to describe what is in front of you."
        else:
            from agents.vision.vlm_analyzer import VLMAnalyzer
            try:
                vlm = await VLMAnalyzer().analyze_scene(
                    image_base64=req.frame_b64.split(",", 1)[-1],
                    zone_id=req.zone_id, language=req.language, worker_query=transcript)
                answer = (vlm.get("spoken_response") or vlm.get("scene_description")
                          or "I could not interpret that scene.")
                detail["vlm"] = vlm
            except Exception as e:
                answer = "The scene description model is unavailable right now."
                detail["error"] = f"{type(e).__name__}: {e}"

    elif intent == "measure":
        if not req.frame_b64:
            answer = "Point the camera at what you want measured and ask again."
        else:
            import asyncio
            from agents.measurement.estimator import MeasurementEngine
            from agents.compliance import spec_registry

            image = _decode(req.frame_b64)
            measurement = await asyncio.to_thread(
                MeasurementEngine().measure, image, "spacing", None, None, None, None,
                "phone", False, True)

            values = measurement.get("measurements") or []
            if measurement.get("status") == "uncalibrated" or not values:
                answer = ("I cannot establish scale in this frame, so I will not give you a "
                          "number. Put a marker in view, or get square to the work.")
            else:
                best = max(values, key=lambda m: float(m.get("confidence") or 0))
                mm = best.get("value_mm") if best.get("value_mm") is not None else best.get("value")
                spec = spec_registry.resolve("spacing", zone_id=req.zone_id, asset_type="rebar")
                if spec is None:
                    answer = (f"I measure {mm:.0f} millimetres, but there is no spacing "
                              f"specification on file for zone {req.zone_id}, so I cannot say "
                              f"whether it passes.")
                else:
                    ok = spec.tolerance_min <= float(mm) <= spec.tolerance_max
                    verdict = "within specification" if ok else "outside specification"
                    answer = (f"I measure {mm:.0f} millimetres. The specification is "
                              f"{spec.expected_value:.0f}, tolerance {spec.tolerance_min:.0f} to "
                              f"{spec.tolerance_max:.0f}. That is {verdict}.")
                    compliance = {"verdict": "PASS" if ok else "FAIL",
                                  "measured_mm": float(mm), "spec": spec.as_dict()}
                    citations = await _cite_for(f"{spec.parameter} tolerance {spec.standard_ref}",
                                                req.project_id)
                    if citations:
                        answer += f" The governing document is {citations[0]['source']}."

    else:  # knowledge
        citations = await _cite_for(transcript, req.project_id)
        if citations:
            answer = (f"From {citations[0]['source']}: "
                      f"{_speakable(citations[0]['excerpt'])}")
        else:
            answer = ("I could not find anything in the indexed project documents that "
                      "answers that. Nothing has been made up to fill the gap.")

    # -- 3. say it out loud ----------------------------------------------
    audio_b64, tts_backend = _speak(answer, req.mode)

    # -- 4. log it, so the dashboard shows a real interaction -------------
    try:
        from api.routes.interactions import record_interaction
        await record_interaction(
            kind=f"voice_{intent}", worker_id=req.worker_id, zone_code=req.zone_id,
            query=transcript, result=answer,
            verdict=(compliance or {}).get("verdict"),
            agent_chain=f"A5:STT -> {'A7:RAG' if citations else intent} -> A8:TTS",
            latency_ms=(time.perf_counter() - t0) * 1000,
            project_id=req.project_id,
        )
    except Exception as e:
        print(f"[worker] interaction log skipped: {e}")

    return {
        "status": "ok",
        "transcript": transcript,
        "stt_backend": stt_backend,
        "intent": intent,
        "answer": answer,
        "citations": citations,
        "measurement": measurement,
        "compliance": compliance,
        "audio_base64": audio_b64,
        "tts_backend": tts_backend,
        "spoken_ok": bool(audio_b64),
        "detail": detail,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


async def _cite_for(query: str, project_id: str) -> list[dict]:
    try:
        from api.routes.rfi_draft import _cite
        cites = await _cite(query, project_id, top_k=2)
        return [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in cites]
    except Exception as e:
        print(f"[worker] retrieval unavailable: {e}")
        return []


@router.get("/status")
async def status():
    """What the worker device can rely on right now."""
    from agents.voice import stt as stt_mod
    from agents.voice import tts as tts_mod

    try:
        from agents.edge.runtime import get_detector
        det = get_detector()
        edge = {"available": bool(det.ready), "error": det.load_error}
    except Exception as e:
        edge = {"available": False, "error": f"{type(e).__name__}: {e}"}

    return {
        "safety_loop": {"detector": edge, "repeat_after_s": HAZARD_REPEAT_S},
        "question_loop": {
            "stt": stt_mod.status(),
            "vlm": {"backend": "gemini", "available": bool(os.getenv("GEMINI_API_KEY"))},
            "tts": tts_mod.status(),
            "intents": ["describe", "measure", "knowledge"],
        },
        "tracked_workers": list(_last_hazard.keys()),
    }
