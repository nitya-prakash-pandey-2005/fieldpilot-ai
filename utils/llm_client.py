import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

LLM_BACKEND = os.getenv("LLM_BACKEND", "mock")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

def get_llm_response(system_prompt: str, user_prompt: str, temperature: float = 0.2, api_key: str = None) -> str:
    """
    Unified LLM Client handling gemini, mock, vllm, and groq backends with graceful fallbacks.
    Returns JSON string (expected by predictors).
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
                    "responseMimeType": "application/json"
                }
            }
            resp = requests.post(url, headers=headers, json=data, timeout=30)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"[LLM Client] Gemini failed: {e}")
            raise Exception(f"Gemini API Error: {e}")

    if LLM_BACKEND == "mock":
        return _mock_rfi_prediction()
        
    if LLM_BACKEND == "groq":
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "llama3-8b-8192", # Groq fast model
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": temperature,
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data, timeout=10)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[LLM Client] Groq failed: {e}. Falling back to mock.")
            return _mock_rfi_prediction()

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
        return _mock_rfi_prediction()


def _mock_rfi_prediction() -> str:
    """
    Returns a properly shaped PredictedRFI JSON object as a string.
    """
    mock_data = {
        "zone_id": "A12",
        "prediction_horizon_days": 14,
        "rfi_risk_score": 0.87,
        "predicted_rfis": [
            {
                "prediction_id": "pred-mock-1234",
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
