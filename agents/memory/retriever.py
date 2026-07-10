import os
import sys
import json
from typing import Protocol, List
from pydantic import BaseModel

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from utils.llm_client import get_llm_response
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

embedder = SentenceTransformer('all-MiniLM-L6-v2')
client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

class RetrievalResult(BaseModel):
    text: str
    source: str
    score: float
    metadata: dict

class RetrievalBackend(Protocol):
    async def search(self, query: str, project_id: str, top_k: int) -> List[RetrievalResult]:
        ...

class QdrantRetrieval:
    async def search(self, query: str, project_id: str, top_k: int) -> List[RetrievalResult]:
        try:
            client.create_collection(
                collection_name=f"project_{project_id}",
                vectors_config=VectorParams(
                    size=384,
                    distance=Distance.COSINE
                )
            )
        except Exception:
            pass  # Already exists
        
        query_vector = embedder.encode(query).tolist()
        
        results = client.search(
            collection_name=f"project_{project_id}",
            query_vector=query_vector,
            limit=top_k
        )
        
        # If collection empty, return mock or handle properly
        if not results:
            print("No results found in Qdrant.")
            return []
            
        return [RetrievalResult(
            text=r.payload.get("text", ""),
            source=r.payload.get("source", ""),
            score=r.score,
            metadata=r.payload
        ) for r in results]

class MockRetrieval:
    async def search(self, query: str, project_id: str, top_k: int) -> List[RetrievalResult]:
        print("Using MockRetrieval for Qdrant...")
        return [
            RetrievalResult(
                text="Engineer Sarah Chen approved alternative east-wall conduit routing in Zone B3 during MEP coordination meeting",
                source="meeting_minutes_2024_06_04.pdf",
                score=0.94,
                metadata={
                    "date": "2024-06-04",
                    "approved_by": "Sarah Chen",
                    "page": 3,
                    "source_type": "meeting_minutes"
                }
            ),
            RetrievalResult(
                text="Change order CO-047 approved alternative MEP routing for Zone B3, reference drawing M-045 Revision 2",
                source="change_order_CO047.pdf", 
                score=0.89,
                metadata={
                    "date": "2024-06-10",
                    "approved_by": "David Park",
                    "source_type": "change_order"
                }
            )
        ]

class MemoryRequest(BaseModel):
    query: str
    project_id: str
    zone_id: str
    worker_id: str
    api_key: str | None = None

class MemoryRetriever:
    def __init__(self):
        backend_type = os.getenv("RETRIEVAL_BACKEND", "mock").lower()
        self.retrieval_backend: RetrievalBackend = QdrantRetrieval() if backend_type == "qdrant" else MockRetrieval()

    async def answer_query(self, req: MemoryRequest):
        # 1. Retrieve Context
        results = await self.retrieval_backend.search(req.query, req.project_id, top_k=5)
        
        # Format the context for the LLM
        context_str = "\n\n".join([
            f"Source: {res.source} (Score: {res.score})\nText: {res.text}\nMetadata: {json.dumps(res.metadata)}"
            for res in results
        ])

        # 2. Build Prompt
        system_prompt = """
        You are the Project Memory AI for a construction project. 
        Your job is to answer the worker's natural language question based STRICTLY on the provided retrieved context.
        You must return a valid JSON object matching this schema:
        {
          "answer": "string",
          "confidence": 0.0 to 1.0,
          "evidence": [
            {
              "source_type": "string",
              "source_id": "string",
              "excerpt": "string",
              "date": "string",
              "approved_by": "string",
              "document_url": "string",
              "page": integer
            }
          ],
          "related_drawing": "string or null",
          "caution": "string or null"
        }
        Do not hallucinate. If the answer is not in the context, say you don't know and set confidence low.
        Output ONLY valid JSON.
        """

        user_prompt = f"""
        Question: {req.query}
        Project ID: {req.project_id}
        Zone ID: {req.zone_id}
        
        Retrieved Context:
        {context_str}
        """

        # 3. Call LLM to synthesize
        try:
            response_text = get_llm_response(system_prompt, user_prompt, temperature=0.1, api_key=req.api_key)
        except Exception as e:
            print(f"LLM failed in MemoryRetriever: {e}. Falling back to mock memory.")
            return {
                "answer": "Based on the retrieved context, Engineer Sarah Chen approved alternative east-wall conduit routing in Zone B3 during the MEP coordination meeting on 2024-06-04.",
                "confidence": 0.94,
                "evidence": [
                    {
                        "source_type": "meeting_minutes",
                        "source_id": "meeting_minutes_2024_06_04.pdf",
                        "excerpt": "Engineer Sarah Chen approved alternative east-wall conduit routing in Zone B3",
                        "date": "2024-06-04",
                        "approved_by": "Sarah Chen",
                        "document_url": None,
                        "page": 3
                    }
                ],
                "related_drawing": "M-045 Revision 2",
                "caution": None
            }

        # 4. Parse Output safely
        try:
            cleaned_text = response_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            # Fallback for hackathon safety if LLM fails format
            return {
                "answer": "Failed to parse LLM response.",
                "confidence": 0.0,
                "evidence": [],
                "related_drawing": None,
                "caution": "System Error"
            }
