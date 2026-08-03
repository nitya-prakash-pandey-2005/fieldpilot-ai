import os
import json
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

LLM_BACKEND = os.getenv("LLM_BACKEND", "mock")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

def get_llm_response(system_prompt: str, user_prompt: str, temperature: float = 0.2,
                     api_key: str = None, zone_id: str = "A12",
                     json_mode: bool = True) -> str:
    """
    Unified LLM Client handling gemini, mock, vllm, and groq backends with graceful fallbacks.

    json_mode=True (the default, preserving the behaviour every existing caller
    relies on) forces structured JSON output — correct for the predictors that
    parse the result.

    json_mode=False is required by callers that want PROSE. Every backend below
    previously hardcoded JSON output, so a caller asking for an RFI body or a
    spoken answer got a JSON object back and had to discard it; Agent 6's RFI
    drafter was silently falling through to its template on every single call
    because of this.

    Note the fallback asymmetry: on failure the groq/vllm branches return an
    RFI-shaped mock, which is only meaningful to the RFI predictor. Prose
    callers must therefore validate what they get back rather than trusting it
    (rfi_draft.py rejects a response that starts with '{').
    """
    if api_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            data = {
                "contents": [
                    {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
                ],
                "generationConfig": {
                    "temperature": temperature,
                    **({"responseMimeType": "application/json"} if json_mode else {}),
                }
            }
            resp = requests.post(url, headers=headers, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"[LLM Client] Gemini failed: {e}")
            raise Exception(f"Gemini API Error: {e}")

    if LLM_BACKEND == "mock":
        return _mock_rfi_prediction(zone_id)
        
    if LLM_BACKEND == "groq":
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                # llama3-8b-8192 was Groq's fast model at the time this was
                # written; Groq has since decommissioned it (confirmed live
                # against /v1/models — the account's currently active text
                # models are llama-3.3-70b-versatile, llama-3.1-8b-instant,
                # and the openai/gpt-oss-* family). Every real call was
                # failing with a 400 model_decommissioned error, silently
                # caught below and replaced with the RFI-shaped mock
                # payload — which broke Project Memory Q&A in particular,
                # since its response shape has no "answer" key at all.
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                **({"response_format": {"type": "json_object"}} if json_mode else {}),
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data, timeout=10)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[LLM Client] Groq failed: {e}. Falling back to mock.")
            return _mock_rfi_prediction(zone_id)

    # Default to vLLM
    try:
        headers = {"Content-Type": "application/json"}
        data = {
            "model": "qwen", # or whatever model is loaded in vLLM
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature
        }
        resp = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=data, timeout=5)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[LLM Client] vLLM failed at {LLM_BASE_URL}: {e}. Falling back to mock.")
        return _mock_rfi_prediction(zone_id)


def _mock_rfi_prediction(zone_id: str = "A12") -> str:
    """
    Returns a properly shaped PredictedRFI JSON object as a string.
    Each call gets a fresh prediction_id and honors the requested zone_id so
    concurrent per-zone callers (e.g. the RFIs page fanning out one request
    per zone) don't all collide on the same hardcoded id/zone.
    """
    mock_data = {
        "zone_id": zone_id,
        "prediction_horizon_days": 14,
        "rfi_risk_score": 0.87,
        "predicted_rfis": [
            {
                "prediction_id": f"pred-mock-{uuid.uuid4().hex[:8]}",
                "rfi_category": "rebar_overlap_ambiguity",
                "probability": 0.87,
                "basis": "14 similar RFIs in 8 comparable projects using same design pattern",
                "similar_historical_rfis": ["RFI-2023-0412", "RFI-2022-0889"],
                "recommended_pre_action": "Engineer to clarify lap splice length at column C4 junction before Zone A12 rebar installation begins",
                "drawing_sections_to_clarify": ["S-101 Detail 4A", "S-102 Section B-B"]
            }
        ],
        "confidence": 0.82
    }
    return json.dumps(mock_data)
