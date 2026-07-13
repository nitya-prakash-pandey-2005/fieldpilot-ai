import os
import json
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class VLMAnalyzer:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY") or "dummy-key-for-demo"
        if not self.api_key:
            print("WARNING: GROQ_API_KEY not set. VLM Analyzer will fail.")
        self.client = Groq(api_key=self.api_key)
        self.model_name = "llama-3.2-11b-vision-preview"
        print(f"VLM loaded via Groq API: {self.model_name}")

    async def analyze_scene(
        self,
        image_base64: str,
        zone_id: str,
        language: str = "en",
        worker_query: str = None,
        project_context: str = ""
    ) -> dict:
        
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

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{system_prompt}\n\nWorker question: {query}"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                        },
                    },
                ],
            }
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
                response_format={"type": "json_object"}
            )
            
            output = response.choices[0].message.content
            
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                # Extract JSON from output if there's markdown wrapping
                start = output.find('{')
                end = output.rfind('}') + 1
                return json.loads(output[start:end])
            
        except Exception as e:
            print(f"VLM Analysis Error: {e}")
            return {
                "scene_description": f"Error analyzing scene: {str(e)}",
                "work_type": "Unknown",
                "safety_hazards": [],
                "compliance_issues": [],
                "urgency": "low",
                "spoken_response": "I encountered an error analyzing this scene.",
                "engineer_alert_needed": False,
                "confidence": 0.0
            }

    @classmethod
    def warmup(cls):
        print("Warming up VLM (Groq API)...")
