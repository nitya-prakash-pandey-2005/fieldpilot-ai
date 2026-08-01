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
from agents.drawing.indexer import EMBEDDING_MODEL, EMBEDDING_DIM, collection_name

# Standardized on the SAME embedding model + collection-naming scheme as
# agents/drawing/indexer.py (previously this used all-MiniLM-L6-v2 against
# "project_{project_id}", while the drawing indexer used bge-small-en-v1.5
# against a single global "drawings_vectors" — two RAG paths that never saw
# each other's data despite sharing a Qdrant instance).
embedder = SentenceTransformer(EMBEDDING_MODEL)
client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=float(os.getenv("QDRANT_TIMEOUT", "2.0")))

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
        name = collection_name(project_id)
        try:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE
                )
            )
        except Exception:
            pass  # Already exists

        query_vector = embedder.encode(query).tolist()

        # QdrantClient.search() was removed in newer qdrant-client versions
        # in favor of query_points(), which wraps results in a
        # QueryResponse (.points) instead of returning a bare list.
        response = client.query_points(
            collection_name=name,
            query=query_vector,
            limit=top_k
        )
        results = response.points

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
        # Qdrant is already provisioned (docker-compose.yml) and populated
        # by drawing ingestion, so it's the real default now rather than a
        # hardcoded mock that silently shadowed it. Set RETRIEVAL_BACKEND=mock
        # to force the mock path (e.g. offline demo without Qdrant running).
        backend_type = os.getenv("RETRIEVAL_BACKEND", "qdrant").lower()
        self.retrieval_backend: RetrievalBackend = QdrantRetrieval() if backend_type == "qdrant" else MockRetrieval()

    async def answer_query(self, req: MemoryRequest):
        # 1. Retrieve Context
        results = await self.retrieval_backend.search(req.query, req.project_id, top_k=5)

        # No real LLM configured for this request (no GROQ_API_KEY/LLM_BACKEND
        # set and no per-request Gemini key) — get_llm_response's "mock"
        # branch returns a fixed RFI-shaped payload meant for the Predictive
        # RFI agent, which would silently mismatch this endpoint's schema.
        # Skip the LLM entirely and return the REAL retrieved Qdrant matches
        # ungrounded-by-an-LLM instead of a canned narrative — no answer is
        # synthesized, but nothing is fabricated either.
        llm_configured = bool(req.api_key) or os.getenv("LLM_BACKEND", "mock").lower() != "mock"
        if not llm_configured:
            resp = self._ungrounded_response(results)
            if results:
                resp["caution"] = "No LLM configured (set GROQ_API_KEY) — showing raw matching passages instead of a synthesized answer."
            return resp

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
            print(f"LLM failed in MemoryRetriever: {e}. Falling back to raw retrieved matches.")
            resp = self._ungrounded_response(results)
            resp["caution"] = f"AI synthesis unavailable ({e}) — showing raw matching passages instead."
            return resp

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
            parsed = json.loads(cleaned_text)
            if not isinstance(parsed, dict) or "answer" not in parsed:
                raise json.JSONDecodeError("unexpected shape", cleaned_text, 0)
            return parsed
        except json.JSONDecodeError:
            resp = self._ungrounded_response(results)
            resp["caution"] = "AI response was malformed — showing raw matching passages instead."
            return resp

    def _ungrounded_response(self, results: List[RetrievalResult]) -> dict:
        """
        Builds a response straight from real Qdrant matches with no LLM
        synthesis layered on top — used whenever no LLM is configured, the
        LLM call fails, or its output can't be parsed. Never fabricates a
        narrative; `answer` stays null so the frontend can render this
        distinctly from a real synthesized answer.
        """
        if not results:
            return {
                "answer": None,
                "confidence": 0.0,
                "evidence": [],
                "related_drawing": None,
                "caution": "No matching documents found in project memory for this query.",
            }
        return {
            "answer": None,
            "confidence": round(results[0].score, 2),
            "evidence": [
                {
                    "source_type": r.metadata.get("source_type", "document"),
                    "source_id": r.source,
                    "excerpt": r.text[:400],
                    "date": r.metadata.get("date"),
                    "approved_by": r.metadata.get("approved_by"),
                    "document_url": None,
                    "page": r.metadata.get("page"),
                }
                for r in results
            ],
            "related_drawing": None,
            "caution": None,
        }
