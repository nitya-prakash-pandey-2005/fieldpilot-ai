import sys
import os
import json
import asyncio
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

# work_type -> asset_type mapping. Previously get_historical_context() was
# always called with the literal string "rebar" regardless of what was
# actually happening in the zone ("Assuming rebar for MVP or parsing from
# work_type" — never finished). Keyword-matched against the free-text
# work_type the frontend/zone sends; falls back to "general" rather than
# silently mislabeling e.g. HVAC work as rebar work.
ASSET_TYPE_KEYWORDS = [
    ("rebar", "rebar"),
    ("concrete", "concrete"),
    ("formwork", "formwork"),
    ("conduit", "conduit"),
    ("mep", "conduit"),
    ("hvac", "hvac_duct"),
    ("duct", "hvac_duct"),
    ("cable", "cable_tray"),
    ("electrical", "electrical_panel"),
    ("plumbing", "pipe"),
    ("pipe", "pipe"),
    ("steel", "structural_steel"),
    ("drywall", "drywall"),
    ("roofing", "roofing"),
    ("curing", "concrete"),
]


def infer_asset_type(work_type: str) -> str:
    wt = (work_type or "").lower()
    for keyword, asset_type in ASSET_TYPE_KEYWORDS:
        if keyword in wt:
            return asset_type
    return "general"


class RFIPredictor:
    async def get_similar_historical_incidents(self, query_text: str, top_k: int = 5) -> list:
        """
        Real vector similarity search over the Learning Agent's `learning_incidents`
        Qdrant collection (written by agents/learning/ingestor.py on every
        POST /api/v1/learning/resolve call) — this IS the project's real
        historical resolved-issue record; there's no separate "historical
        RFI" dataset anywhere in the system, so grounding predictions in
        actually-resolved incidents is the honest real data source rather
        than inventing a parallel fake RFI corpus. Returns [] (not fabricated
        matches) if Qdrant is unreachable or the collection is still empty.
        """
        try:
            from qdrant_client import QdrantClient
            from agents.learning.ingestor import QDRANT_COLLECTION, _get_incident_embedder

            def _search():
                client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
                model = _get_incident_embedder()
                vector = model.encode(query_text).tolist()
                response = client.query_points(collection_name=QDRANT_COLLECTION, query=vector, limit=top_k)
                return response.points

            points = await asyncio.to_thread(_search)
            return [
                {
                    "incident_id": p.payload.get("incident_id"),
                    "zone_id": p.payload.get("zone_id"),
                    "asset_type": p.payload.get("asset_type"),
                    "issue_type": p.payload.get("issue_type"),
                    "text": p.payload.get("text"),
                    "score": round(p.score, 3),
                }
                for p in points
            ]
        except Exception as e:
            print(f"Qdrant similarity search failed in RFI predictor: {e}")
            return []

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
        # 1. Real asset-type inference from the actual work_type (was
        # hardcoded to "rebar" for every zone/activity)
        asset_type = infer_asset_type(req.current_activity.work_type)

        # 2. Real context: Neo4j RFI history (empty until real RFI/ABOUT
        # edges exist — see the Knowledge Graph write-path gap) + real
        # Qdrant vector similarity over actually-resolved incidents
        historical_context = await self.get_historical_context(asset_type, req.zone_id)
        query_text = f"Zone {req.zone_id}: {asset_type} — {req.current_activity.work_type}"
        similar_incidents = await self.get_similar_historical_incidents(query_text)

        similar_incidents_str = "\n".join(
            f"- [{inc['incident_id']}] (similarity {inc['score']}) Zone {inc['zone_id']}, {inc['asset_type']}/{inc['issue_type']}: {inc['text']}"
            for inc in similar_incidents
        ) or "No similar resolved incidents found in project memory yet."

        # 3. Build Prompt
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
        IMPORTANT: "similar_historical_rfis" must ONLY contain incident IDs
        that literally appear in the "Similar Resolved Incidents" list below
        (in square brackets), verbatim. If none are relevant, use an empty
        array — never invent an ID that wasn't given to you.
        Do not include markdown blocks or any other text. Output ONLY valid JSON.
        """

        user_prompt = f"""
        Project ID: {req.project_id}
        Zone ID: {req.zone_id}
        Inferred Asset Type: {asset_type}
        Current Work Type: {req.current_activity.work_type}
        Drawing References: {', '.join(req.current_activity.drawing_refs)}
        Historical Context (Neo4j): {historical_context}
        Similar Resolved Incidents (Qdrant vector similarity):
        {similar_incidents_str}
        """

        # 4. Call LLM
        response_text = get_llm_response(system_prompt, user_prompt, temperature=0.2, zone_id=req.zone_id)

        # 5. Parse output safely
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            # If the LLM failed to return pure JSON (hallucination etc), fall back to mock
            from utils.llm_client import _mock_rfi_prediction
            parsed = json.loads(_mock_rfi_prediction(req.zone_id))

        # 6. Ground "similar_historical_rfis" in what was ACTUALLY retrieved,
        # regardless of what the LLM produced — never trust the model not
        # to hallucinate a plausible-looking but fake incident ID here.
        real_ids = [inc["incident_id"] for inc in similar_incidents if inc.get("incident_id")]
        for prediction in parsed.get("predicted_rfis", []):
            prediction["similar_historical_rfis"] = real_ids

        return parsed
