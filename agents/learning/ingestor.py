import os
import sys
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from neo4j import AsyncGraphDatabase

from agents.learning.retry_queue import queue_failed_write

logger = logging.getLogger(__name__)

# Make the api/ package (models.*, db.py) importable — same convention as
# agents/compliance/validator.py and agents/notification/router.py.
_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
if _API_DIR not in sys.path:
    sys.path.append(_API_DIR)

QDRANT_COLLECTION = "learning_incidents"

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
        self.neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        # Matches the real credential in docker-compose.yml's NEO4J_AUTH and
        # api/db.py's hardcoded NEO4J_AUTH — this previously defaulted to
        # "password", which never matched the actual container and would
        # have failed to authenticate regardless of whether Neo4j was up.
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "askthewall_dev")

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
        """
        Writes to the same unified `fieldpilot` Postgres DB/ORM as
        everything else (FieldIssue, ComplianceEvent, NotificationAudit).
        Previously this connected via raw asyncpg to a separate `askthewall`
        database that no longer exists — this table (and the whole
        Learning Agent) would have failed to connect at all against the
        current unified docker-compose stack until this fix.
        """
        from db import async_session
        from sqlalchemy import select
        from models.resolved_incident import ResolvedIncident

        async with async_session() as session:
            existing = await session.execute(
                select(ResolvedIncident).where(ResolvedIncident.incident_id == payload.incident_id)
            )
            if existing.scalar_one_or_none() is not None:
                return  # ON CONFLICT (incident_id) DO NOTHING, same as before

            session.add(ResolvedIncident(
                incident_id=payload.incident_id,
                project_id=payload.project_id,
                zone_id=payload.zone_id,
                asset_type=payload.asset_type,
                issue_type=payload.issue_type,
                measurement_at_detection=payload.measurement_at_detection,
                spec_value=payload.spec_value,
                resolution=json.dumps(payload.resolution),
                photos=json.dumps(payload.photos),
                outcome_metrics=json.dumps(payload.outcome_metrics),
                tags=json.dumps(payload.tags),
            ))
            await session.commit()

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
        """
        Real embed + upsert into Qdrant — previously this unconditionally
        raised ConnectionRefusedError regardless of environment (a
        permanent stub, not a real attempt that happened to fail). Qdrant
        now runs fine in the unified docker-compose.yml (verified for RAG
        elsewhere in this codebase), so there's no reason for this to stay
        fake. Uses the same BAAI/bge-small-en-v1.5 model standardized
        across agents/drawing/indexer.py and agents/memory/retriever.py so
        incidents are embedded compatibly with the rest of the RAG stack.
        """
        import asyncio
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Distance, VectorParams, PointStruct
        from agents.drawing.indexer import EMBEDDING_MODEL, EMBEDDING_DIM

        resolution = payload.resolution or {}
        summary = (
            f"Zone {payload.zone_id}: {payload.asset_type} {payload.issue_type.replace('_', ' ')}. "
            f"Measured {payload.measurement_at_detection}, spec {payload.spec_value}. "
            f"Resolution: {resolution.get('action_taken', '')} {resolution.get('resolution_notes', '')}"
        ).strip()

        def _embed_and_upsert():
            model = _get_incident_embedder()
            client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
            try:
                collections = client.get_collections().collections
                if not any(c.name == QDRANT_COLLECTION for c in collections):
                    client.create_collection(
                        collection_name=QDRANT_COLLECTION,
                        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
                    )
            except Exception:
                pass  # already exists

            vector = model.encode(summary).tolist()
            client.upsert(
                collection_name=QDRANT_COLLECTION,
                points=[PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, payload.incident_id)),
                    vector=vector,
                    payload={
                        "incident_id": payload.incident_id,
                        "zone_id": payload.zone_id,
                        "asset_type": payload.asset_type,
                        "issue_type": payload.issue_type,
                        "text": summary,
                    },
                )],
            )

        # SentenceTransformer.encode + QdrantClient are both blocking calls.
        await asyncio.to_thread(_embed_and_upsert)


_incident_embedder = None


def _get_incident_embedder():
    """Lazily load and cache the embedding model across calls (module-level singleton)."""
    global _incident_embedder
    if _incident_embedder is None:
        from sentence_transformers import SentenceTransformer
        from agents.drawing.indexer import EMBEDDING_MODEL
        _incident_embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _incident_embedder
