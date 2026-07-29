import os
import uuid
import json
import hashlib
from datetime import datetime, timezone
from neo4j import AsyncGraphDatabase

neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "askthewall_dev")

# Same keyword-matching convention as agents/predictive_rfi/predictor.py's
# infer_asset_type — kept as a separate copy here rather than a shared
# import since the input text differs (asset_id/measurement parameter here,
# work_type there) and the two agents shouldn't need to coordinate a shared
# module just for a handful of keyword tuples.
ASSET_TYPE_KEYWORDS = [
    ("rebar", "rebar"),
    ("concrete", "concrete"),
    ("formwork", "formwork"),
    ("conduit", "conduit"),
    ("hvac", "hvac_duct"),
    ("duct", "hvac_duct"),
    ("cable", "cable_tray"),
    ("electrical", "electrical_panel"),
    ("plumbing", "pipe"),
    ("pipe", "pipe"),
    ("steel", "structural_steel"),
    ("drywall", "drywall"),
    ("roofing", "roofing"),
]


def infer_asset_type(*hints: str) -> str:
    text = " ".join(h or "" for h in hints).lower()
    for keyword, asset_type in ASSET_TYPE_KEYWORDS:
        if keyword in text:
            return asset_type
    return "general"


async def write_inspection(
    zone_id: str,
    asset_id: str,
    result: str,
    confidence: float,
    asset_type_hint: str = "",
    inspector_id: str = "compliance_agent",
) -> bool:
    """
    Real write-path for the Knowledge Graph queries in
    agents/knowledge_graph/queries.py (get_zone_risk_score,
    get_failing_assets) — previously nothing in the codebase ever created
    Asset/Inspection nodes or the LOCATED_IN/INSPECTS relationships those
    queries assume exist (scripts/seed_demo_data.py only ever created
    Zone/Asset/Drawing/RFI, no Inspection node, no LOCATED_IN/INSPECTS
    edges), so those two queries always returned empty against a real,
    running Neo4j. Call this on every compliance validation result
    (PASS/FAIL/UNCERTAIN), not just FAIL, so the risk-score ratio
    (failures / total inspections) is real.

    Returns False (never raises) on Neo4j failure — an Inspection write
    failing must never break compliance validation itself, matching the
    "log and continue" pattern already used for notification dispatch in
    ComplianceEngine.validate().
    """
    asset_type = infer_asset_type(asset_id, asset_type_hint)
    try:
        driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        cypher = """
        MERGE (z:Zone {id: $zone_id})
        MERGE (a:Asset {id: $asset_id})
        SET a.type = $asset_type
        MERGE (a)-[:LOCATED_IN]->(z)
        CREATE (i:Inspection {id: $inspection_id, result: $result, date: datetime(), confidence: $confidence, inspector_id: $inspector_id})
        CREATE (i)-[:INSPECTS]->(a)
        """
        async with driver.session() as session:
            await session.run(
                cypher,
                zone_id=zone_id,
                asset_id=asset_id,
                asset_type=asset_type,
                inspection_id=str(uuid.uuid4()),
                result=result,
                confidence=confidence,
                inspector_id=inspector_id,
            )
        await driver.close()
        return True
    except Exception as e:
        print(f"[KnowledgeGraph] Failed to write Inspection node: {e}")
        return False


async def commit_asset_version(asset_id: str, changes: dict, author: str) -> dict:
    """
    Real write-path for POST /api/v1/version-control/commit — previously a
    pure stub returning a fixed literal commit_hash ("a1b2c3d4e5f6") and
    never touching the database regardless of input. Creates a real
    :AssetVersion node linked to the (now-real, see write_inspection) Asset
    node via :HAS_VERSION, ordered by timestamp so get_asset_version_history
    can return genuine history instead of 2 hardcoded rows.

    commit_hash is a real content hash (asset_id + changes + author +
    timestamp) — not cryptographically meaningful, just a real derived
    identifier rather than a fixed placeholder string.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    version_id = str(uuid.uuid4())
    commit_hash = hashlib.sha256(
        f"{asset_id}:{json.dumps(changes, sort_keys=True)}:{author}:{timestamp}".encode()
    ).hexdigest()[:12]

    try:
        driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        cypher = """
        MERGE (a:Asset {id: $asset_id})
        CREATE (v:AssetVersion {
            id: $version_id, commit_hash: $commit_hash, author: $author,
            changes: $changes_json, timestamp: datetime($timestamp)
        })
        CREATE (a)-[:HAS_VERSION]->(v)
        """
        async with driver.session() as session:
            await session.run(
                cypher,
                asset_id=asset_id,
                version_id=version_id,
                commit_hash=commit_hash,
                author=author,
                changes_json=json.dumps(changes),
                timestamp=timestamp,
            )
        await driver.close()
        return {"status": "success", "commit_hash": commit_hash, "version_id": version_id, "timestamp": timestamp}
    except Exception as e:
        print(f"[KnowledgeGraph] Failed to write AssetVersion: {e}")
        return {"status": "error", "commit_hash": None, "error": str(e)}


async def get_asset_version_history(asset_id: str) -> list:
    """Real read-path counterpart to commit_asset_version — replaces the
    hardcoded 2-entry history GET /api/v1/version-control/history/{asset_id}
    previously returned for every asset_id regardless of input."""
    try:
        driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        cypher = """
        MATCH (a:Asset {id: $asset_id})-[:HAS_VERSION]->(v:AssetVersion)
        RETURN v.id AS version_id, v.commit_hash AS commit_hash, v.author AS author,
               v.changes AS changes, v.timestamp AS timestamp
        ORDER BY v.timestamp DESC
        """
        async with driver.session() as session:
            result = await session.run(cypher, asset_id=asset_id)
            records = await result.data()
        await driver.close()
        history = []
        for rec in records:
            changes = {}
            try:
                changes = json.loads(rec["changes"]) if rec.get("changes") else {}
            except (json.JSONDecodeError, TypeError):
                pass
            history.append({
                "version_id": rec["version_id"],
                "commit_hash": rec["commit_hash"],
                "author": rec["author"],
                "changes": changes,
                "timestamp": str(rec["timestamp"]) if rec.get("timestamp") else None,
            })
        return history
    except Exception as e:
        print(f"[KnowledgeGraph] Failed to read AssetVersion history: {e}")
        return []
