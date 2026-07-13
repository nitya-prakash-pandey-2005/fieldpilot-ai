from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
from pydantic import BaseModel
from db import get_neo4j_session
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.knowledge_graph.queries import get_zone_risk_score
from agents.knowledge_graph.schema import setup_constraints

# Setup constraints on module load if DB is up
# Session will be obtained within endpoints

router = APIRouter(prefix="/api/v1/graph", tags=["Knowledge Graph (Agent 4)"])

class NodeCreate(BaseModel):
    label: str
    properties: Dict[str, Any]

class RelationshipCreate(BaseModel):
    source_id: str
    target_id: str
    rel_type: str
    properties: Dict[str, Any] = {}

class QueryRequest(BaseModel):
    query: str
    parameters: Dict[str, Any] = {}

@router.post("/nodes")
async def create_node(node: NodeCreate):
    session = get_neo4j_session()
    if not session:
        raise HTTPException(status_code=500, detail="Neo4j connection not available")
    
    # Construct Cypher query dynamically (simplified for MVP)
    props_str = ", ".join([f"{k}: ${k}" for k in node.properties.keys()])
    query = f"CREATE (n:{node.label} {{{props_str}}}) RETURN n"
    
    try:
        with session.begin_transaction() as tx:
            result = tx.run(query, **node.properties)
            record = result.single()
            if record:
                return {"status": "success", "node": dict(record["n"])}
            return {"status": "success", "message": "Node created but not returned"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@router.post("/query")
async def execute_cypher(req: QueryRequest):
    session = get_neo4j_session()
    if not session:
        raise HTTPException(status_code=500, detail="Neo4j connection not available")
    
    try:
        with session.begin_transaction() as tx:
            result = tx.run(req.query, **req.parameters)
            records = [dict(r) for r in result]
            return {"status": "success", "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@router.get("/zone/{zone_id}/status")
async def get_zone_status(zone_id: str):
    session = get_neo4j_session()
    if not session:
        raise HTTPException(status_code=500, detail="Neo4j connection not available")
    
    try:
        risk_data = get_zone_risk_score(session, zone_id)
        return {"status": "success", "data": risk_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@router.get("/project/{project_id}/zones")
async def get_project_zones(project_id: str):
    session = get_neo4j_session()
    if not session:
        raise HTTPException(status_code=500, detail="Neo4j connection not available")
    
    try:
        with session.begin_transaction() as tx:
            result = tx.run("MATCH (z:Zone) RETURN z.id AS id, z.x AS x, z.y AS y")
            zones_info = [{"id": r["id"], "x": r["x"], "y": r["y"]} for r in result]
            
        data = []
        for z in zones_info:
            risk_data = get_zone_risk_score(session, z["id"])
            risk_score = risk_data.get("risk_score") or 0.0
            data.append({
                "zone_id": z["id"], 
                "name": f"Zone {z['id']}",
                "risk_score": risk_score,
                "status": "critical" if risk_score > 0.7 else ("amber" if risk_score > 0.3 else "green"),
                "active_issues": risk_data.get("failures") or 0,
                "coordinates": {"x": z["x"] or 0, "y": z["y"] or 0}
            })
            
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
