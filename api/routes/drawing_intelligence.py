from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Dict, Any, List
from pydantic import BaseModel
import re
import uuid
import sys
import os
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.drawing.parser import DocumentParser, extract_dimensions_from_text
from agents.drawing.indexer import DocumentIndexer, collection_name

from db import get_neo4j_session

router = APIRouter(prefix="/api/v1/drawing", tags=["Drawing Intelligence (Agent 3)"])

# Initialize singletons lazily within endpoints or on startup
parser = DocumentParser()
indexer = DocumentIndexer()

@router.post("/parse")
async def parse_drawing(file: UploadFile = File(...), is_tabular: bool = False, project_id: str = "default-project"):
    # Save uploaded file to temp directory
    temp_dir = os.path.join(os.path.dirname(__file__), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Parse document using strategy pattern
        text = parser.parse(temp_file_path, is_tabular=is_tabular)
        if not text:
            raise HTTPException(status_code=500, detail="Failed to parse document.")

        # Extract specs
        specs = await extract_dimensions_from_text(text, file.filename)

        # Index document chunks — scoped to project_id so it's retrievable
        # through the Project Memory Q&A path (agents/memory/retriever.py),
        # which searches the same project_{project_id}_drawings collection.
        doc_id = str(uuid.uuid4())
        indexed_count = indexer.index_document(doc_id, text, project_id=project_id, source=file.filename)

        return {
            "status": "success", 
            "filename": file.filename,
            "document_id": doc_id,
            "extracted_dimensions": specs,
            "indexed_chunks": indexed_count,
            "message": "File parsed and indexed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

class IndexRequest(BaseModel):
    document_id: str
    text_chunks: List[str]
    project_id: str = "default-project"
    source: str | None = None

@router.post("/index")
async def index_drawing(req: IndexRequest):
    # Optional endpoint if we want to bypass the parser and manually index text
    doc_id = str(uuid.uuid4()) if req.document_id == "new" else req.document_id
    combined_text = "\n".join(req.text_chunks)
    count = indexer.index_document(doc_id, combined_text, project_id=req.project_id, source=req.source)
    return {"status": "success", "indexed_chunks": count, "document_id": doc_id}


_DRAWING_NUMBER_HINT = re.compile(r"([A-Z]{1,3}-\d{2,4})")


def _lookup_drawing_metadata(number: str) -> dict | None:
    """Best-effort join against real Neo4j Drawing nodes (written by
    scripts/seed_demo_data.py / version-control scans) keyed by a drawing
    number guessed from the uploaded filename. Returns None (never a
    fabricated name) if there's no match."""
    session = get_neo4j_session()
    if not session:
        return None
    try:
        result = session.run(
            """
            MATCH (d:Drawing {number: $number})
            WHERE NOT (d)-[:SUPERSEDES]->(:Drawing)
            RETURN d.revision AS revision, d.approved_date AS approved_date,
                   d.discipline AS discipline, d.approved_by AS approved_by
            """,
            number=number,
        )
        record = result.single()
        return dict(record) if record else None
    except Exception:
        return None
    finally:
        session.close()


@router.get("/list")
async def list_drawings(project_id: str = "default-project"):
    """
    Real list of documents ingested through /parse or /index for this
    project — grouped from actual Qdrant chunk payloads (document_id,
    source, chunk_index), the only durable record of what's been indexed
    (there is no separate Postgres "drawings" table). Where the uploaded
    filename matches a real Neo4j Drawing node's number, real revision/
    approval metadata is merged in; otherwise those fields are omitted
    rather than filled with a fabricated name/date. Previously the
    frontend had no endpoint to call here at all and rendered a fixed
    mock array unconditionally.
    """
    name = collection_name(project_id)
    try:
        points, _ = indexer.qdrant_client.scroll(
            collection_name=name, limit=1000, with_payload=True
        )
    except Exception:
        return {"status": "success", "data": []}

    documents: Dict[str, Dict[str, Any]] = {}
    for point in points:
        payload = point.payload or {}
        doc_id = payload.get("document_id")
        if not doc_id:
            continue
        entry = documents.setdefault(doc_id, {
            "document_id": doc_id,
            "source": payload.get("source", doc_id),
            "chunk_count": 0,
        })
        entry["chunk_count"] += 1

    drawings = []
    for doc in documents.values():
        match = _DRAWING_NUMBER_HINT.search(doc["source"].upper())
        number = match.group(1) if match else doc["source"]
        meta = _lookup_drawing_metadata(number) if match else None

        drawings.append({
            "id": doc["document_id"],
            "number": number,
            "discipline": (meta or {}).get("discipline") or "General",
            "latest_revision": (meta or {}).get("revision"),
            "latest_date": (meta or {}).get("approved_date"),
            "approved_by": (meta or {}).get("approved_by"),
            "indexed_chunks": doc["chunk_count"],
            "source_file": doc["source"],
        })

    drawings.sort(key=lambda d: d["number"])
    return {"status": "success", "data": drawings}
