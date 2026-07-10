import sys
import os
import json
from pydantic import BaseModel
from typing import List
import uuid

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from utils.llm_client import get_llm_response
from neo4j import AsyncGraphDatabase

neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "askthewall_dev")

class CurrentActivity(BaseModel):
    work_type: str
    drawing_refs: List[str]
    scheduled_completion: str

class RFIRequest(BaseModel):
    project_id: str
    zone_id: str
    current_activity: CurrentActivity

class RFIPredictor:
    async def get_historical_context(self, asset_type: str, zone_id: str) -> str:
        try:
            driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
            async with driver.session() as session:
                result = await session.run("""
                    MATCH (r:RFI)-[:ABOUT]->(a:Asset)
                    WHERE a.type = $asset_type
                    AND r.status = 'resolved'
                    RETURN r.subject as subject,
                           r.resolution_notes as notes,
                           r.created_date as date
                    ORDER BY r.created_date DESC
                    LIMIT 5
                """, asset_type=asset_type)
                
                records = await result.data()
            await driver.close()
            
            if records:
                context_lines = []
                for rec in records:
                    context_lines.append(f"- On {rec['date']}, RFI '{rec['subject']}' was resolved: {rec['notes']}")
                return "\n".join(context_lines)
        except Exception as e:
            print(f"Neo4j query failed: {e}")
            
        # Seed fallback — always returns something
        return f"In similar projects, historical RFIs were raised regarding {asset_type} due to ambiguous drawings."

    async def predict(self, req: RFIRequest):
        # 1. Real context retrieval from Neo4j
        historical_context = await self.get_historical_context("rebar", req.zone_id)  # Assuming rebar for MVP or parsing from work_type
        
        # 2. Build Prompt
        system_prompt = """
        You are an expert construction engineer and AI assistant. Your job is to predict future RFIs (Requests For Information) based on current zone activity and historical project data.
        You must return a valid JSON object matching this schema:
        {
          "zone_id": "string",
          "prediction_horizon_days": 14,
          "rfi_risk_score": 0.0 to 1.0,
          "predicted_rfis": [
            {
              "prediction_id": "string (uuid)",
              "rfi_category": "string",
              "probability": 0.0 to 1.0,
              "basis": "string",
              "similar_historical_rfis": ["string"],
              "recommended_pre_action": "string",
              "drawing_sections_to_clarify": ["string"]
            }
          ],
          "confidence": 0.0 to 1.0
        }
        Do not include markdown blocks or any other text. Output ONLY valid JSON.
        """
        
        user_prompt = f"""
        Project ID: {req.project_id}
        Zone ID: {req.zone_id}
        Current Work Type: {req.current_activity.work_type}
        Drawing References: {', '.join(req.current_activity.drawing_refs)}
        Historical Context: {historical_context}
        """
        
        # 3. Call LLM
        response_text = get_llm_response(system_prompt, user_prompt, temperature=0.2)
        
        # 4. Parse output safely
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # If the LLM failed to return pure JSON (hallucination etc), fallback to mock
            from utils.llm_client import _mock_rfi_prediction
            return json.loads(_mock_rfi_prediction())
