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
    # Shared factory: falls back to embedded storage when no container is
    # running (Follow.md §4), and guarantees one client per process — embedded
    # mode holds an exclusive lock on its directory, so a second one fails.
    import sys as _sys
    _sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from utils.qdrant_config import get_client as _get_qdrant
    qdrant_client = _get_qdrant()
except Exception as e:
    print(f"Failed to connect to Qdrant: {e}")
    qdrant_client = None

# SQLAlchemy Setup (PostgreSQL, with a SQLite fallback)
import socket
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# POSTGRES_USER=fieldpilot POSTGRES_PASSWORD=fieldpilot_password POSTGRES_DB=fieldpilot
DEFAULT_POSTGRES_URL = "postgresql+asyncpg://fieldpilot:fieldpilot_password@localhost:5432/fieldpilot"

# The SQLite file every model was already written to be compatible with — see
# models/notification.py and models/resolved_incident.py, which use portable
# JSON/TEXT columns rather than Postgres JSONB/ARRAY "for the same
# sqlite-fallback-compat reason".
SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fieldpilot.db")
SQLITE_URL = f"sqlite+aiosqlite:///{SQLITE_PATH}"


def _reachable(url: str, timeout: float = 1.0) -> bool:
    """TCP-probe the database host before SQLAlchemy tries to connect.

    asyncpg raises ConnectionRefusedError from inside the lifespan handler,
    which FastAPI turns into 'Application startup failed. Exiting.' — the whole
    API dies because one optional service is down. A 1s probe here converts
    that hard failure into a documented degradation.
    """
    try:
        parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
        host, port = parsed.hostname, parsed.port
        if not host:
            return False
        with socket.create_connection((host, port or 5432), timeout=timeout):
            return True
    except OSError:
        return False


_explicit_url = os.getenv("DATABASE_URL")

if _explicit_url:
    # An explicitly configured URL is never second-guessed: if someone set
    # DATABASE_URL, silently redirecting their writes to a local SQLite file
    # would be far worse than failing loudly.
    SQLALCHEMY_DATABASE_URL = _explicit_url
    DB_BACKEND = "explicit"
elif _reachable(DEFAULT_POSTGRES_URL):
    SQLALCHEMY_DATABASE_URL = DEFAULT_POSTGRES_URL
    DB_BACKEND = "postgres"
else:
    SQLALCHEMY_DATABASE_URL = SQLITE_URL
    DB_BACKEND = "sqlite"
    print(
        "[DB] Postgres unreachable at localhost:5432 — falling back to SQLite at "
        f"{SQLITE_PATH}\n"
        "[DB] This is a supported degraded mode: all tables are created and seeded "
        "on startup. Start Postgres (docker compose up -d postgres) or set "
        "DATABASE_URL for the full stack."
    )

engine = create_async_engine(SQLALCHEMY_DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session
