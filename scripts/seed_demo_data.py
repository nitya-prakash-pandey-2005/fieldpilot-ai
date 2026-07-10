import os
import sys
import uuid
import random
import asyncio
import asyncpg
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

def seed_neo4j():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "askthewall_dev")
    
    print("Connecting to Neo4j to seed data...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            zones = [
                {"id": "A12", "x": 105, "y": 105},
                {"id": "B3", "x": 305, "y": 105},
                {"id": "C7", "x": 505, "y": 105}
            ]
            for z in zones:
                session.run("MERGE (z:Zone {id: $id}) SET z.x = $x, z.y = $y", **z)
            
            session.run("MERGE (a:Asset {id: 'Rebar-A12', type: 'rebar', zone_id: 'A12'})")
            session.run("MERGE (a:Asset {id: 'Column-C4', type: 'column', zone_id: 'B3'})")
            session.run("MERGE (a:Asset {id: 'Wall-East', type: 'wall', zone_id: 'C7'})")
            
            demo_drawings = [
                {"number": "S-101", "revision": "R5", "approved_date": "2024-11-02", "key_changes": "Rebar spacing in Zone A12 changed from 200mm to 150mm"},
                {"number": "S-102", "revision": "R3", "approved_date": "2024-10-15", "key_changes": "Column C4 lap splice clarified"},
                {"number": "M-045", "revision": "R2", "approved_date": "2024-09-20", "key_changes": "East wall conduit routing approved"}
            ]
            for dwg in demo_drawings:
                query = """
                MERGE (d:Drawing {number: $number})
                SET d.revision = $revision,
                    d.approved_date = $approved_date,
                    d.key_changes = $key_changes
                """
                session.run(query, **dwg)
                
            demo_rfis = [
                {"id": "RFI-001", "subject": "Lap splice length at C4", "status": "resolved", "notes": "Splice length is 600mm", "date": "2024-09-15"},
                {"id": "RFI-002", "subject": "Rebar congestion in beam-column joint", "status": "resolved", "notes": "Use smaller diameter bars, increase quantity", "date": "2024-08-20"},
                {"id": "RFI-003", "subject": "Slab edge rebar detailing", "status": "resolved", "notes": "Provide U-bars at all free edges", "date": "2024-07-10"},
                {"id": "RFI-004", "subject": "Rebar spacing tolerance", "status": "resolved", "notes": "Tolerance is +/- 10mm as per ACI", "date": "2024-06-05"},
                {"id": "RFI-005", "subject": "Clear cover to rebar", "status": "resolved", "notes": "Maintain 50mm clear cover", "date": "2024-05-12"}
            ]
            for rfi in demo_rfis:
                query = """
                MERGE (r:RFI {id: $id})
                SET r.subject = $subject,
                    r.status = $status,
                    r.resolution_notes = $notes,
                    r.created_date = $date
                MERGE (a:Asset {id: 'Rebar-A12'})
                MERGE (r)-[:ABOUT]->(a)
                """
                session.run(query, **rfi)
            
        driver.close()
        print("Neo4j successfully seeded.")
    except Exception as e:
        print(f"Failed Neo4j seed: {e}")

def seed_qdrant():
    print("Connecting to Qdrant to seed real embedded documents...")
    try:
        client = QdrantClient(url="http://localhost:6333")
        embedder = SentenceTransformer('all-MiniLM-L6-v2')
        collection_name = "project_P-001"
        
        try:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE)
            )
        except Exception:
            pass  # Already exists
            
        DEMO_DOCUMENTS = [
          {
            "text": "Engineer Sarah Chen approved alternative east-wall conduit routing in Zone B3 during MEP coordination meeting. Reference drawing M-045 Revision 2.",
            "source": "meeting_minutes_2024_06_04.pdf",
            "source_type": "meeting_minutes",
            "date": "2024-06-04",
            "approved_by": "Sarah Chen",
            "zone_ids": ["B3"]
          },
          {
            "text": "Change order CO-047 approved by David Park. Alternative MEP routing Zone B3 confirmed. Cost neutral. Effective immediately.",
            "source": "change_order_CO047.pdf", 
            "source_type": "change_order",
            "date": "2024-06-10",
            "approved_by": "David Park",
            "zone_ids": ["B3"]
          },
          {
            "text": "Zone A12 rebar spacing specification: 150mm center to center, tolerance ±10mm. Per ACI 318-19 Section 7.7.1. Drawing S-101 Revision 5.",
            "source": "S-101-R5.pdf",
            "source_type": "drawing",
            "date": "2024-11-02",
            "zone_ids": ["A12"]
          },
          {
            "text": "RFI-2024-0089 resolved: Column C4 lap splice length confirmed as 600mm by structural engineer James Wilson. See drawing S-102 detail 4A.",
            "source": "RFI_2024_0089_resolved.pdf",
            "source_type": "rfi",
            "date": "2024-09-15",
            "zone_ids": ["A12"]
          },
          {
            "text": "Safety inspection Zone C7: All fire suppression pipe clearances verified. Minimum 50mm clearance maintained. Signed off by inspector Mike Torres.",
            "source": "inspection_report_C7_2024.pdf",
            "source_type": "inspection",
            "date": "2024-10-20",
            "zone_ids": ["C7"]
          }
        ]
        
        points = []
        for i, doc in enumerate(DEMO_DOCUMENTS):
            vector = embedder.encode(doc["text"]).tolist()
            points.append(PointStruct(
                id=i+1,
                vector=vector,
                payload=doc
            ))
            
        client.upsert(collection_name=collection_name, points=points)
        print(f"Qdrant successfully seeded with {len(points)} real embedded documents.")
    except Exception as e:
        print(f"Failed Qdrant seed: {e}")

async def seed_postgres():
    uri = os.getenv("POSTGRES_URI", "postgresql://atw_user:atw_dev_password@localhost:5432/askthewall")
    print("Connecting to Postgres to seed incidents...")
    try:
        conn = await asyncpg.connect(uri)
        
        for _ in range(47):
            await conn.execute('''
            INSERT INTO resolved_incidents (
                incident_id, project_id, zone_id, asset_type, issue_type,
                measurement_at_detection, spec_value, resolution, outcome_metrics
            ) VALUES (
                gen_random_uuid(), 'P-001', 'A12', 'rebar', 'spacing_violation',
                200.0, 150.0, '{"action": "reworked"}', '{"cost_avoided_usd": 3978, "time_saved": 4}'
            )
            ''')
            
        for z in ["A12", "C7"]:
            await conn.execute(f'''
            INSERT INTO compliance_events (
                zone_id, asset_type, severity, measured_value, spec_value, deviation_pct, worker_id
            ) VALUES (
                '{z}', 'rebar', 'high', 200.0, 150.0, 33.3, 'W-001'
            )
            ''')
            
        await conn.close()
        print("Postgres successfully seeded.")
    except Exception as e:
        print(f"Failed Postgres seed: {e}")

if __name__ == "__main__":
    seed_neo4j()
    seed_qdrant()
    asyncio.run(seed_postgres())
