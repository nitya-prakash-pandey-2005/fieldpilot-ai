import os
import json
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
import asyncpg
from neo4j import AsyncGraphDatabase

from agents.learning.retry_queue import queue_failed_write

logger = logging.getLogger(__name__)

class IncidentResolutionPayload(BaseModel):
    incident_id: str
    project_id: str
    zone_id: str
    asset_type: str
    issue_type: str
    measurement_at_detection: float
    spec_value: float
    resolution: Dict[str, Any]
    photos: Dict[str, str] = {}
    outcome_metrics: Dict[str, Any]
    tags: List[str] = []

@dataclass
class IngestResult:
    postgresql: bool
    neo4j: bool
    qdrant: bool

class LearningIngestor:
    def __init__(self):
        self.pg_uri = os.getenv("POSTGRES_URI", "postgresql://postgres:password@localhost:5432/askthewall")
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    async def ingest(self, payload: IncidentResolutionPayload) -> dict:
        """
        Ingests the resolved incident across PostgreSQL, Neo4j, and Qdrant.
        Strict error handling rules apply.
        """
        response = {
            "incident_id": payload.incident_id,
            "status": "success",
            "storage": {
                "postgresql": {"success": False},
                "neo4j": {"success": False, "retry_queued": False},
                "qdrant": {"success": False, "mock_used": False}
            }
        }
        
        # 1. PostgreSQL (Source of Truth)
        try:
            await self._write_postgres(payload)
            response["storage"]["postgresql"]["success"] = True
        except Exception as e:
            # If PostgreSQL fails, raise exception to trigger 500
            raise Exception(f"PostgreSQL Write Failed: {e}")

        # 2. Neo4j (Graph)
        try:
            await self._write_neo4j(payload)
            response["storage"]["neo4j"]["success"] = True
        except Exception as e:
            logger.warning(f"Neo4j write failed: {e}")
            await queue_failed_write("neo4j", payload.incident_id, payload.model_dump())
            response["storage"]["neo4j"]["success"] = False
            response["storage"]["neo4j"]["error"] = str(e)
            response["storage"]["neo4j"]["retry_queued"] = True
            response["status"] = "partial_success"
            response["warning"] = "Neo4j write failed. Incident saved to PostgreSQL. Graph link will retry."

        # 3. Qdrant (Memory Vector)
        try:
            await self._write_qdrant(payload)
            response["storage"]["qdrant"]["success"] = True
            response["storage"]["qdrant"]["mock_used"] = False
        except Exception as e:
            logger.warning(f"Qdrant write failed: {e}")
            await queue_failed_write("qdrant", payload.incident_id, payload.model_dump())
            response["storage"]["qdrant"]["success"] = False
            response["storage"]["qdrant"]["error"] = str(e)
            response["storage"]["qdrant"]["retry_queued"] = True
            # Does not downgrade status to partial_success, just a warning in the field (as per prompt)
            
        return response

    async def _write_postgres(self, payload: IncidentResolutionPayload):
        conn = await asyncpg.connect(self.pg_uri)
        try:
            await conn.execute('''
                INSERT INTO resolved_incidents (
                    incident_id, project_id, zone_id, asset_type, issue_type,
                    measurement_at_detection, spec_value, resolution, photos, outcome_metrics, tags
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (incident_id) DO NOTHING
            ''', 
            payload.incident_id, payload.project_id, payload.zone_id, payload.asset_type, payload.issue_type,
            payload.measurement_at_detection, payload.spec_value, json.dumps(payload.resolution),
            json.dumps(payload.photos), json.dumps(payload.outcome_metrics), payload.tags)
        finally:
            await conn.close()

    async def _write_neo4j(self, payload: IncidentResolutionPayload):
        # We attempt a real connection. If Neo4j isn't running, it raises an exception which is caught by ingest()
        driver = AsyncGraphDatabase.driver(self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password))
        
        engineer_id = payload.resolution.get("resolved_by", "Unknown")
        cypher = """
        MERGE (i:Incident {id: $incident_id})
        SET i.type = $issue_type, i.resolved = true
        MERGE (e:Engineer {id: $engineer_id})
        MERGE (i)-[:RESOLVED_BY]->(e)
        MERGE (z:Zone {id: $zone_id})
        MERGE (i)-[:OCCURRED_IN]->(z)
        """
        async with driver.session() as session:
            await session.run(cypher, 
                              incident_id=payload.incident_id, 
                              issue_type=payload.issue_type,
                              engineer_id=engineer_id,
                              zone_id=payload.zone_id)
        await driver.close()

    async def _write_qdrant(self, payload: IncidentResolutionPayload):
        # We simulate a Qdrant failure since Qdrant isn't natively running on windows in this environment
        # and there is no Qdrant client installed.
        raise ConnectionRefusedError("Qdrant connection refused")
