from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.memory.retriever import MemoryRetriever, MemoryRequest, client as qdrant_client
from agents.drawing.indexer import DocumentIndexer, collection_name

router = APIRouter(prefix="/api/v1/memory", tags=["Project Memory (Agent 7)"])

_indexer = DocumentIndexer()

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
    api_key = request.headers.get("X-Gemini-API-Key")
    if api_key:
        req.api_key = api_key

    try:
        return await retriever.answer_query(req)
    except Exception as e:
        # Qdrant or the LLM being unreachable is an infrastructure outage, not a
        # malformed request. Returning 500 here blanks the dashboard's Ask-AI
        # panel with a red error; returning a structured "I can't answer and
        # here's why" keeps the UI coherent and tells the worker what to do.
        #
        # It must NOT invent an answer: a fabricated citation from the project
        # memory agent is the single most damaging thing this system could
        # output, because the whole value proposition is that its answers are
        # backed by a real approval or spec.
        msg = str(e)
        unreachable = any(s in msg.lower() for s in
                          ("refused", "connection", "timed out", "10061", "unreachable"))
        print(f"[MEMORY] query failed: {msg}")
        return {
            "status": "degraded",
            "answer": None,
            "confidence": 0.0,
            "evidence": [],
            "error": ("Project memory store is unreachable, so no cited answer can be "
                      "given. Start it with `docker compose up -d qdrant`."
                      if unreachable else f"Memory query failed: {msg}"),
            "error_class": "store_unreachable" if unreachable else "query_failed",
        }

class IndexMemoryRequest(BaseModel):
    document_content: str
    project_id: str = "default-project"
    source: str | None = None
    source_type: str = "document"  # email | meeting_minutes | whatsapp | change_order | rfi | document
    date: str | None = None
    approved_by: str | None = None


@router.post("/index")
async def index_memory(req: IndexMemoryRequest):
    """
    Real chunk -> BGE-M3-family embed -> Qdrant upsert into the SAME
    project_{project_id}_drawings collection MemoryRetriever/QdrantRetrieval
    already searches (agents/drawing/indexer.py's collection-naming
    convention) — so anything indexed here is immediately retrievable
    through POST /memory/query. Previously this was a no-op stub that
    always returned success without touching any store.
    """
    if not req.document_content.strip():
        raise HTTPException(status_code=400, detail="document_content is empty")

    doc_id = str(uuid.uuid4())
    count = _indexer.index_document(
        doc_id,
        req.document_content,
        project_id=req.project_id,
        source=req.source or f"{req.source_type}_{doc_id[:8]}",
        extra_payload={
            "source_type": req.source_type,
            "date": req.date,
            "approved_by": req.approved_by,
        },
    )
    return {
        "status": "success",
        "document_id": doc_id,
        "indexed_chunks": count,
        "message": f"Indexed {count} chunks into project memory." if count else "Nothing indexed — check Qdrant connectivity.",
    }
