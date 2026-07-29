"""
DB Init — FieldPilot AI
--------------------------
Creates every SQLAlchemy table (Zone, FieldIssue, Project, Asset,
Observation, ComplianceEvent, NotificationAudit — all sharing the Base in
api/models/zones.py) against the single unified `fieldpilot` Postgres DB.

api/main.py's FastAPI lifespan already does this automatically on server
startup — this script exists for setting up the DB standalone (CI, a fresh
docker-compose volume, or local testing) without booting the whole API.

Previously this ran hand-written raw SQL against a SECOND, separate
Postgres database (`askthewall`) for compliance_events/notification_audit,
disconnected from the `fieldpilot` DB the rest of the app used. Both tables
are now real SQLAlchemy models in the one DB — see agents/compliance/
validator.py and agents/notification/router.py.

Run:
  python scripts/init_db.py
"""

import os
import sys
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.join(ROOT, "api")
sys.path.insert(0, API_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))


async def init_db():
    from db import engine
    from models.zones import Base
    from models.issues import FieldIssue           # noqa: F401 (registers table on Base.metadata)
    from models.project import Project, Asset       # noqa: F401
    from models.observation import Observation      # noqa: F401
    from models.compliance import ComplianceEvent   # noqa: F401
    from models.notification import NotificationAudit  # noqa: F401
    from models.resolved_incident import ResolvedIncident  # noqa: F401

    print(f"Connecting to {engine.url.database} to create tables…")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"✅ Tables ready: {', '.join(sorted(Base.metadata.tables.keys()))}")


if __name__ == "__main__":
    asyncio.run(init_db())
