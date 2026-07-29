from fastapi import APIRouter, HTTPException, Request
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.memory.retriever import MemoryRetriever, MemoryRequest, client as qdrant_client
from agents.drawing.indexer import collection_name

router = APIRouter(prefix="/api/v1/memory", tags=["Project Memory (Agent 7)"])

# Initialize Retriever
retriever = MemoryRetriever()

@router.get("/stats")
async def get_memory_stats(project_id: str = "default-project"):
    """
    Real Qdrant collection size for this project's memory index — lets the
    frontend explain an empty/thin answer honestly ("0 passages indexed yet")
    instead of it looking like a search bug.
    """
    name = collection_name(project_id)
    try:
        info = qdrant_client.get_collection(collection_name=name)
        return {
            "status": "success",
            "data": {
                "collection": name,
                "indexed_passages": info.points_count or 0,
                "llm_configured": os.getenv("LLM_BACKEND", "mock").lower() != "mock",
            },
        }
    except Exception:
        return {
            "status": "success",
            "data": {
                "collection": name,
                "indexed_passages": 0,
                "llm_configured": os.getenv("LLM_BACKEND", "mock").lower() != "mock",
            },
        }

@router.post("/query")
async def query_memory(req: MemoryRequest, request: Request):
    """
    RAG over past RFIs, project specs, and previous issues to provide historical context.
    """
    try:
        api_key = request.headers.get("X-Gemini-API-Key")
        if api_key:
            req.api_key = api_key
        # Await the async answer_query method
        result = await retriever.answer_query(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/index")
async def index_memory(document_content: str):
    """
    Index a resolved issue or approved RFI into the project memory vector database.
    """
    return {"status": "success", "message": "Document indexed successfully into long-term memory (MVP Stub)."}
