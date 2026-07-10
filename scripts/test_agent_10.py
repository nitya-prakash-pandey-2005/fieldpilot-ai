import sys
import os
import uuid
import asyncio
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
from agents.learning.ingestor import LearningIngestor, IncidentResolutionPayload
from agents.learning.exporter import DatasetExporter
from fastapi import Response

def create_payload(incident_id: str = None) -> IncidentResolutionPayload:
    if incident_id is None:
        incident_id = str(uuid.uuid4())
    return IncidentResolutionPayload(
        incident_id=incident_id,
        project_id="P-001",
        zone_id="A12",
        asset_type="rebar",
        issue_type="spacing_violation",
        measurement_at_detection=190.0,
        spec_value=150.0,
        resolution={
            "action_taken": "Rebar repositioned to 152mm",
            "time_to_resolve_hours": 2.5,
            "resolved_by": "E-005",
            "resolution_notes": "Temporary support form caused misalignment. Corrected before concrete pour.",
            "rework_required": False
        },
        outcome_metrics={
            "cost_avoided_usd": 12000,
            "time_avoided_hours": 16
        },
        tags=["rebar", "spacing", "formwork_interference", "zone_a12"]
    )

async def run_tests():
    ingestor = LearningIngestor()
    exporter = DatasetExporter()

    print("\n--- Test 1: Full pipeline insertion (Postgres works, Qdrant mock fails, Neo4j fails) ---")
    p1 = create_payload()
    res1 = await ingestor.ingest(p1)
    print(res1)
    assert res1["storage"]["postgresql"]["success"] is True
    # In my env, Neo4j is down, so we expect 207 behavior internally mapped as partial_success
    assert res1["status"] == "partial_success"

    print("\n--- Test 2: Neo4j failure (207 Partial Success & Redis Queue) ---")
    p2 = create_payload()
    # Force Neo4j to fail by giving it bad URI
    original_uri = ingestor.neo4j_uri
    ingestor.neo4j_uri = "bolt://localhost:9999"
    res2 = await ingestor.ingest(p2)
    ingestor.neo4j_uri = original_uri
    print(res2)
    assert res2["status"] == "partial_success"
    assert res2["storage"]["postgresql"]["success"] is True
    assert res2["storage"]["neo4j"]["success"] is False
    assert res2["storage"]["neo4j"]["retry_queued"] is True

    print("\n--- Test 3: Export 3 pair types ---")
    jsonl = await exporter.export_jsonl()
    lines = [json.loads(line) for line in jsonl.strip().split('\n') if line.strip()]
    assert len(lines) >= 3, "Should have at least 3 pairs"
    types = [line["export_type"] for line in lines[:3]]
    assert "resolution" in types
    assert "prediction" in types
    assert "memory" in types
    print("Exported JSONL sample (first 3):")
    for l in lines[:3]:
        print(l)

    print("\n--- Test 4: Verify Stats aggregations ---")
    stats = await exporter.get_stats()
    print(stats)
    assert stats["total_incidents_learned"] >= 2
    assert stats["total_cost_avoided_usd"] >= 24000
    assert stats["most_common_root_cause"] == "formwork_interference"

    print("\n--- Test 5: Verify bulk dataset exports ---")
    # Insert 5 more
    for _ in range(5):
        await ingestor.ingest(create_payload())
    
    stats_after = await exporter.get_stats()
    print(f"Total incidents after bulk insert: {stats_after['total_incidents_learned']}")
    assert stats_after["jsonl_pairs_available"] == stats_after["total_incidents_learned"] * 3
    
    print("\n✅ All Agent 10 Tests Passed!")

if __name__ == "__main__":
    asyncio.run(run_tests())
