import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

# Was Groq (llama-3.2-11b-vision-preview) — Groq has since decommissioned
# every vision-capable model on this account (confirmed live against
# /v1/models: only text/audio models remain). Switched to Gemini, which the
# project already has a working key for (agents/voice/tts.py uses the same
# GEMINI_API_KEY for TTS) and which supports real image+text input with
# structured JSON output via generateContent, same REST pattern as tts.py
# and utils/llm_client.py's Gemini branch.
GEMINI_VLM_MODEL = os.getenv("GEMINI_VLM_MODEL", "gemini-flash-latest")

# gemini | gemma. Gemma 4 runs locally (agents/vision/gemma_analyzer.py) and is
# the offline/edge-consistent path: no API key, no network, Apache-2.0. Gemini
# stays the default because it needs neither 8B of weights on disk nor a GPU, so
# an unconfigured checkout behaves exactly as it did before this backend existed.
#
# The two are NOT silently interchangeable and must never fall back to each
# other: "edge mode reached for the network" is the specific dishonesty the edge
# path in agents/edge/runtime.py refuses to commit, and the same rule applies
# here. If the selected backend cannot serve, it says so and stops.
VLM_BACKEND = os.getenv("VLM_BACKEND", "gemini").lower()


class VLMAnalyzer:
    def __init__(self, backend: str = None):
        self.backend = (backend or VLM_BACKEND).lower()

        if self.backend == "gemma":
            # Imported lazily: gemma_analyzer is import-safe on transformers 4.x,
            # but there is no reason to pull torch into a Gemini-only process.
            from agents.vision.gemma_analyzer import GemmaAnalyzer
            self._gemma = GemmaAnalyzer.instance()
            self.model_name = self._gemma.model_id
            print(f"VLM backend: gemma (local) — {self.model_name}")
            return

        self._gemma = None
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            print("WARNING: GEMINI_API_KEY not set. VLM Analyzer will fail.")
        self.model_name = GEMINI_VLM_MODEL
        print(f"VLM loaded via Gemini API: {self.model_name}")

    async def analyze_scene(
        self,
        image_base64: str,
        zone_id: str,
        language: str = "en",
        worker_query: str = None,
        project_context: str = ""
    ) -> dict:

        if self._gemma is not None:
            return await self._gemma.analyze_scene(
                image_base64, zone_id, language, worker_query, project_context
            )

        query = worker_query or "What is happening in this construction scene? Any safety issues or compliance concerns?"

        system_prompt = f"""You are an AI construction site assistant seeing through a worker's smart glasses.
Zone: {zone_id}
Language to respond in: {language}
Project context: {project_context}

Analyze the scene and respond EXACTLY in this JSON format:
{{
  "scene_description": "what you see",
  "work_type": "type of work",
  "safety_hazards": ["array of strings, empty if none"],
  "compliance_issues": ["array of strings, empty if none"],
  "urgency": "low", // one of: low, medium, high, critical
  "spoken_response": "response in worker language ({language})",
  "engineer_alert_needed": false,
  "confidence": 0.9
}}
"""

        if not self.api_key:
            return self._error_result("GEMINI_API_KEY not configured")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": f"{system_prompt}\n\nWorker question: {query}"},
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        try:
            resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=30)
            resp.raise_for_status()
            output = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                # Extract JSON from output if there's markdown wrapping
                start = output.find('{')
                end = output.rfind('}') + 1
                return json.loads(output[start:end])

        except Exception as e:
            print(f"VLM Analysis Error: {e}")
            return self._error_result(str(e))

    def _error_result(self, error: str) -> dict:
        return {
            "scene_description": f"Error analyzing scene: {error}",
            "work_type": "Unknown",
            "safety_hazards": [],
            "compliance_issues": [],
            "urgency": "low",
            "spoken_response": "I encountered an error analyzing this scene.",
            "engineer_alert_needed": False,
            "confidence": 0.0
        }

    async def identify_objects(self, image_base64: str, hint: str = "") -> dict:
        """Open-vocabulary "what is this" — Gemma-only.

        Deliberately not emulated on the Gemini path. Gemini could answer it, but
        the point of this call is the local brain; quietly serving it from an API
        would make an offline capability claim that a network cable disproves.
        """
        if self._gemma is None:
            return {
                "status": "unavailable",
                "reason": f"identify_objects requires VLM_BACKEND=gemma (current: {self.backend})",
                "objects": [],
                "backend": self.backend,
            }
        return await self._gemma.identify_objects(image_base64, hint)

    @classmethod
    def warmup(cls):
        if VLM_BACKEND == "gemma":
            from agents.vision.gemma_analyzer import GemmaAnalyzer
            print("Warming up VLM (Gemma 4, local — first load pulls ~8B weights)...")
            GemmaAnalyzer.instance()._load()
            return
        print("Warming up VLM (Gemini API)...")
