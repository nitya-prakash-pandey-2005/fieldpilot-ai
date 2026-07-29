from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db import get_neo4j_session, get_db
from models.zones import Zone
from models.issues import FieldIssue
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from agents.knowledge_graph.queries import get_zone_risk_score
from agents.knowledge_graph.schema import setup_constraints
from auth import require_role, CurrentUser

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
async def create_node(node: NodeCreate, _user: CurrentUser = Depends(require_role("engineer", "admin"))):
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
async def execute_cypher(req: QueryRequest, _user: CurrentUser = Depends(require_role("engineer", "admin"))):
    """
    Raw Cypher passthrough for engineers (per system_prompt.md Section 11.2).
    Previously had NO auth at all — anyone could run arbitrary Cypher
    (including destructive DELETE/DETACH DELETE) against the graph.
    """
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

@router.get("/full")
async def get_full_graph(project_id: str = "default-project", db: AsyncSession = Depends(get_db)):
    """
    Unified graph payload for the Knowledge Graph page: real Postgres
    Project->Zone->Issue nodes (the reliable, always-populated source of
    truth), merged with the real Neo4j Incident->Engineer subgraph that
    agents/learning/ingestor.py._write_neo4j actually writes whenever
    someone resolves an incident via POST /api/v1/learning/resolve. Neo4j
    is queried defensively — if it's down or empty (the common case until
    incidents get resolved), the page still renders the Postgres side and
    `meta.neo4j_available` tells the frontend why the incident layer is
    thin instead of it looking like a bug.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    project_node_id = f"project:{project_id}"
    nodes.append({
        "id": project_node_id,
        "type": "project",
        "label": project_id.replace("-", " ").replace("_", " ").title(),
    })

    zone_result = await db.execute(select(Zone).where(Zone.project_id == project_id))
    zones = zone_result.scalars().all()
    zone_code_to_node_id = {}
    for z in zones:
        node_id = f"zone:{z.id}"
        zone_code_to_node_id[z.zone_code] = node_id
        nodes.append({
            "id": node_id,
            "type": "zone",
            "label": z.name,
            "zone_code": z.zone_code,
            "current_activity": z.current_activity,
            "risk_score": z.risk_score,
            "risk_level": z.risk_level,
            "active_worker_count": z.active_worker_count,
            "open_issue_count": z.open_issue_count,
        })
        edges.append({"source": project_node_id, "target": node_id, "type": "HAS_ZONE"})

    issue_result = await db.execute(select(FieldIssue).where(FieldIssue.project_id == project_id))
    issues = issue_result.scalars().all()
    for i in issues:
        node_id = f"issue:{i.id}"
        nodes.append({
            "id": node_id,
            "type": "issue",
            "label": (i.issue_type or "issue").replace("_", " ").title(),
            "severity": i.severity,
            "status": i.status,
            "description": i.description,
            "zone_code": i.zone_code,
            "worker_id": i.worker_id,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        })
        zone_node_id = zone_code_to_node_id.get(i.zone_code)
        if zone_node_id:
            edges.append({"source": zone_node_id, "target": node_id, "type": "HAS_ISSUE"})

    neo4j_available = False
    session = get_neo4j_session()
    if session:
        try:
            result = session.run("""
                MATCH (i:Incident)-[:OCCURRED_IN]->(z:Zone)
                OPTIONAL MATCH (i)-[:RESOLVED_BY]->(e:Engineer)
                RETURN i.id AS incident_id, i.type AS issue_type, i.resolved AS resolved,
                       z.id AS zone_code, e.id AS engineer_id
                ORDER BY i.id
                LIMIT 150
            """)
            records = [r.data() for r in result]
            neo4j_available = True
            seen_engineers = set()
            for rec in records:
                incident_node_id = f"incident:{rec['incident_id']}"
                nodes.append({
                    "id": incident_node_id,
                    "type": "incident",
                    "label": (rec.get("issue_type") or "incident").replace("_", " ").title(),
                    "resolved": bool(rec.get("resolved")),
                    "zone_code": rec.get("zone_code"),
                })
                zone_node_id = zone_code_to_node_id.get(rec.get("zone_code"))
                if zone_node_id:
                    edges.append({"source": zone_node_id, "target": incident_node_id, "type": "OCCURRED_IN"})
                eng = rec.get("engineer_id")
                if eng:
                    eng_node_id = f"engineer:{eng}"
                    if eng not in seen_engineers:
                        seen_engineers.add(eng)
                        nodes.append({"id": eng_node_id, "type": "engineer", "label": eng})
                    edges.append({"source": incident_node_id, "target": eng_node_id, "type": "RESOLVED_BY"})

            # Real Asset/Inspection nodes — written by
            # agents/compliance/validator.py on every PASS/FAIL/UNCERTAIN
            # validation (see agents/knowledge_graph/writer.py). Previously
            # nothing in the codebase ever created these, so this branch
            # always returned empty; each Asset is colored by its most
            # recent Inspection result rather than listing every inspection
            # as its own node, to keep the graph readable as inspection
            # volume grows.
            asset_result = session.run("""
                MATCH (z:Zone)<-[:LOCATED_IN]-(a:Asset)
                OPTIONAL MATCH (a)<-[:INSPECTS]-(i:Inspection)
                WITH z, a, i
                ORDER BY i.date DESC
                WITH z, a, collect(i)[0] AS latest_inspection, count(i) AS inspection_count
                RETURN z.id AS zone_code, a.id AS asset_id, a.type AS asset_type,
                       latest_inspection.result AS result,
                       latest_inspection.confidence AS confidence,
                       inspection_count
                LIMIT 200
            """)
            for rec in [r.data() for r in asset_result]:
                asset_node_id = f"asset:{rec['asset_id']}"
                nodes.append({
                    "id": asset_node_id,
                    "type": "asset",
                    "label": (rec.get("asset_type") or "asset").replace("_", " ").title(),
                    "asset_type": rec.get("asset_type"),
                    "latest_inspection_result": rec.get("result"),
                    "latest_inspection_confidence": rec.get("confidence"),
                    "inspection_count": rec.get("inspection_count") or 0,
                    "zone_code": rec.get("zone_code"),
                })
                zone_node_id = zone_code_to_node_id.get(rec.get("zone_code"))
                if zone_node_id:
                    edges.append({"source": zone_node_id, "target": asset_node_id, "type": "LOCATED_IN"})
        except Exception:
            neo4j_available = False
        finally:
            session.close()

    return {
        "status": "success",
        "data": {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "neo4j_available": neo4j_available,
                "zone_count": len(zones),
                "issue_count": len(issues),
                "incident_count": sum(1 for n in nodes if n["type"] == "incident"),
                "asset_count": sum(1 for n in nodes if n["type"] == "asset"),
            },
        },
    }


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
        return {"status": "success", "data": [
            {"zone_id": "z-1", "name": "Zone A12", "risk_score": 85, "status": "critical", "active_issues": 2, "coordinates": {"x": 100, "y": 100}},
            {"zone_id": "z-2", "name": "Zone B3", "risk_score": 45, "status": "amber", "active_issues": 2, "coordinates": {"x": 200, "y": 150}},
            {"zone_id": "z-3", "name": "Zone C7", "risk_score": 12, "status": "green", "active_issues": 1, "coordinates": {"x": 300, "y": 200}}
        ]}
    
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
