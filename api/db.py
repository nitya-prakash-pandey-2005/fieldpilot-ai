import os
from neo4j import GraphDatabase
from qdrant_client import QdrantClient

# Neo4j Setup
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_AUTH = ("neo4j", "askthewall_dev")  # default dev auth

try:
    neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
except Exception as e:
    print(f"Failed to connect to Neo4j: {e}")
    neo4j_driver = None

def get_neo4j_session():
    if neo4j_driver:
        return neo4j_driver.session()
    return None

# Qdrant Setup
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
try:
    qdrant_client = QdrantClient(url=QDRANT_URL)
except Exception as e:
    print(f"Failed to connect to Qdrant: {e}")
    qdrant_client = None

def get_qdrant_client():
    return qdrant_client
