import os
from neo4j import GraphDatabase
from qdrant_client import QdrantClient

# Neo4j Setup
# Credentials come from the environment so a real deployment never ships the
# dev password. The defaults match docker-compose.yml's NEO4J_AUTH — change
# both together, or override both with env vars.
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_AUTH = (
    os.getenv("NEO4J_USER", "neo4j"),
    os.getenv("NEO4J_PASSWORD", "askthewall_dev"),
)

# Short timeouts on purpose. The driver connects lazily, so when Neo4j is down
# the failure surfaces at query time — and on the defaults that costs ~4s per
# call while the driver retries. Compliance validation writes an Inspection node
# on every verdict, so those 4s land directly in the worker's alert latency and
# blow the <5s end-to-end budget in system_prompt.md §13.1. Failing fast lets
# the Postgres degradation paths answer immediately instead.
NEO4J_TIMEOUTS = dict(
    connection_timeout=float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "2.0")),
    max_transaction_retry_time=float(os.getenv("NEO4J_RETRY_TIME", "2.0")),
)

try:
    neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH, **NEO4J_TIMEOUTS)
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
    qdrant_client = QdrantClient(url=QDRANT_URL, timeout=float(os.getenv("QDRANT_TIMEOUT", "2.0")))
except Exception as e:
    print(f"Failed to connect to Qdrant: {e}")
    qdrant_client = None

# SQLAlchemy Setup (PostgreSQL)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# POSTGRES_USER=fieldpilot POSTGRES_PASSWORD=fieldpilot_password POSTGRES_DB=fieldpilot
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://fieldpilot:fieldpilot_password@localhost:5432/fieldpilot"
)

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, echo=False
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session
