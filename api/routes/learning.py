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
    import asyncpg
    from datetime import datetime, timedelta
    
    uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
    try:
        conn = await asyncpg.connect(uri)
        
        # Query groups by DATE(created_at) for the last 30 days.
        # Uses JSONB extraction: outcome_metrics->>'cost_avoided_usd'
        query = """
        SELECT 
            DATE(created_at) as trend_date,
            COUNT(*) as incidents,
            SUM(CAST(COALESCE(outcome_metrics->>'cost_avoided_usd', '0') AS FLOAT)) as cost_avoided
        FROM resolved_incidents
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY DATE(created_at)
        ORDER BY trend_date ASC;
        """
        records = await conn.fetch(query)
        await conn.close()
        
        # Format the data for the frontend chart
        data = []
        for r in records:
            data.append({
                "date": r["trend_date"].strftime("%Y-%m-%d"),
                "cost_avoided": float(r["cost_avoided"] or 0),
                "incidents": int(r["incidents"] or 0)
            })
            
        return {
            "status": "success",
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
