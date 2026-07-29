from fastapi import APIRouter
from pydantic import BaseModel
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.version_control.scanner import VersionControlScanner
from agents.knowledge_graph.writer import commit_asset_version, get_asset_version_history

router = APIRouter(prefix="/api/v1/version-control", tags=["Version Control Agent (Agent 8)"])

class ScanRequest(BaseModel):
    frame: str
    project_id: str
    worker_id: str

class CommitRequest(BaseModel):
    asset_id: str
    changes: dict
    author: str

@router.post("/scan")
async def scan_drawing(req: ScanRequest):
    """
    Scans a physical drawing frame via OCR, extracts metadata, and checks for outdated revisions.
    """
    scanner = VersionControlScanner()
    result = scanner.scan_drawing(req.frame)
    return result

@router.post("/commit")
async def commit_changes(req: CommitRequest):
    """
    Commits state changes to the Neo4j graph, creating a new temporal version of an asset.
    """
    result = await commit_asset_version(req.asset_id, req.changes, req.author)
    if result["status"] == "error":
        return {"status": "error", "message": f"Failed to commit state change for {req.asset_id}: {result.get('error')}"}
    return {
        "status": "success",
        "commit_hash": result["commit_hash"],
        "message": f"Successfully committed state change for {req.asset_id}",
    }

@router.get("/history/{asset_id}")
async def get_history(asset_id: str):
    """
    Retrieves the temporal history and state changes for a specific physical or digital asset.
    """
    history = await get_asset_version_history(asset_id)
    return {"asset_id": asset_id, "history": history}
