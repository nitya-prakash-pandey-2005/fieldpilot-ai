from fastapi import APIRouter, HTTPException
import uuid
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.memory.retriever import MemoryRetriever, MemoryRequest

router = APIRouter(prefix="/api/v1/memory", tags=["Project Memory (Agent 7)"])

# Initialize Retriever
retriever = MemoryRetriever()

@router.post("/query")
async def query_memory(req: MemoryRequest):
    """
    RAG over past RFIs, project specs, and previous issues to provide historical context.
    """
    try:
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
