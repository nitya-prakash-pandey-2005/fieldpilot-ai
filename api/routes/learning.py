from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.learning.ingestor import LearningIngestor, IncidentResolutionPayload
from agents.learning.exporter import DatasetExporter

router = APIRouter(prefix="/api/v1/learning", tags=["Learning Agent (Agent 10)"])

ingestor = LearningIngestor()
exporter = DatasetExporter()

@router.post("/resolve")
async def resolve_incident(payload: IncidentResolutionPayload, response: Response):
    """
    Ingests a resolved incident, distributing it to Postgres, Neo4j, and Qdrant.
    Returns 200 on total success, 207 on partial success (Neo4j failure), and 500 on Postgres failure.
    """
    try:
        result = await ingestor.ingest(payload)
        
        if result["status"] == "partial_success":
            response.status_code = 207
            
        return result
    except Exception as e:
        # PostgreSQL failure (or catastrophic code failure)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export-dataset")
async def export_dataset():
    """
    Generates a JSONL dataset from all resolved incidents containing Resolution, Prediction, and Memory pairs.
    """
    try:
        jsonl_data = await exporter.export_jsonl()
        return Response(content=jsonl_data, media_type="application/jsonl")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_stats():
    """
    Aggregates metrics across all resolved incidents to power the executive dashboard.
    """
    try:
        return await exporter.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trends")
async def get_trends():
    """
    Returns daily trend data for cost avoidance and incidents resolved over the last 30 days.
    """
    try:
        data = await exporter.get_trends(days=30)
        return {
            "status": "success",
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recent-incidents")
async def get_recent_incidents(limit: int = 10):
    """
    Returns the most recent resolved incidents (raw rows, not aggregated) —
    powers the Executive Dashboard's "Recent Resolved Incidents" table,
    which previously showed 5 permanently hardcoded rows with no backend
    call despite this data (resolution notes, resolved_by, cost_avoided)
    already existing in the same DatasetExporter used by /stats.
    """
    try:
        import json as _json
        incidents = await exporter._get_all_incidents()
        incidents.sort(key=lambda i: i.get("created_at") or "", reverse=True)
        rows = []
        for inc in incidents[:limit]:
            res_raw = inc.get("resolution") or "{}"
            out_raw = inc.get("outcome_metrics") or "{}"
            res = _json.loads(res_raw) if isinstance(res_raw, str) else (res_raw or {})
            out = _json.loads(out_raw) if isinstance(out_raw, str) else (out_raw or {})
            rows.append({
                "issue": inc["issue_type"].replace("_", " ").title(),
                "zone": inc["zone_id"],
                "asset_type": inc["asset_type"],
                "deviation": f"{inc['measurement_at_detection']} -> {inc['spec_value']}" if inc.get("measurement_at_detection") is not None else "n/a",
                "resolved_by": res.get("resolved_by", "unknown"),
                "time_hours": res.get("time_to_resolve_hours", 0),
                "cost_saved_usd": out.get("cost_avoided_usd", out.get("cost_avoided", 0)),
            })
        return {"status": "success", "data": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
