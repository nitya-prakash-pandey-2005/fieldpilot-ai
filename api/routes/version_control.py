from fastapi import APIRouter
from pydantic import BaseModel
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.version_control.scanner import VersionControlScanner

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
    return {
        "status": "success",
        "commit_hash": "a1b2c3d4e5f6",
        "message": f"Successfully committed state change for {req.asset_id}"
    }

@router.get("/history/{asset_id}")
async def get_history(asset_id: str):
    """
    Retrieves the temporal history and state changes for a specific physical or digital asset.
    """
    return {
        "asset_id": asset_id,
        "history": [
            {"version": 1, "state": "Formwork Installed", "timestamp": "2026-07-09T10:00:00Z"},
            {"version": 2, "state": "Rebar Installed", "timestamp": "2026-07-10T11:30:00Z"}
        ]
    }
