from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Dict, Any, List
from pydantic import BaseModel
import uuid
import sys
import os
import shutil

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.drawing.parser import DocumentParser, extract_dimensions_from_text
from agents.drawing.indexer import DocumentIndexer

router = APIRouter(prefix="/api/v1/drawing", tags=["Drawing Intelligence (Agent 3)"])

# Initialize singletons lazily within endpoints or on startup
parser = DocumentParser()
indexer = DocumentIndexer()

@router.post("/parse")
async def parse_drawing(file: UploadFile = File(...), is_tabular: bool = False):
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
        
        # Index document chunks
        doc_id = str(uuid.uuid4())
        indexed_count = indexer.index_document(doc_id, text)
        
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

@router.post("/index")
async def index_drawing(req: IndexRequest):
    # Optional endpoint if we want to bypass the parser and manually index text
    doc_id = str(uuid.uuid4()) if req.document_id == "new" else req.document_id
    combined_text = "\n".join(req.text_chunks)
    count = indexer.index_document(doc_id, combined_text)
    return {"status": "success", "indexed_chunks": count, "document_id": doc_id}
