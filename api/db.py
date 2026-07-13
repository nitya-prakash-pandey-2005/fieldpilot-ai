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

# SQLAlchemy Setup (SQLite for local dev)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./fieldpilot.db"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session
