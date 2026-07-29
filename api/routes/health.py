from fastapi import APIRouter
import os
import json
import glob
import asyncio

router = APIRouter(prefix="/api/v1/health", tags=["System Health"])

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")


async def _check_postgres() -> bool:
    try:
        from db import engine
        async with engine.connect():
            pass
        return True
    except Exception:
        return False


def _check_neo4j() -> bool:
    try:
        from db import neo4j_driver
        if neo4j_driver is None:
            return False
        neo4j_driver.verify_connectivity()
        return True
    except Exception:
        return False


def _check_qdrant() -> bool:
    try:
        from db import qdrant_client
        if qdrant_client is None:
            return False
        qdrant_client.get_collections()
        return True
    except Exception:
        return False


def _check_groq() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


@router.get("/agents")
async def get_agents_health():
    """
    Returns the live status of the system's agents by actually testing
    connectivity to each backing service. Previously this returned a
    hardcoded dict (`{"drawing": "degraded", "predictive_rfi": "degraded",
    ...}`) regardless of real system state.
    """
    pg_ok = await _check_postgres()
    neo4j_ok = await asyncio.to_thread(_check_neo4j)
    qdrant_ok = await asyncio.to_thread(_check_qdrant)
    groq_ok = _check_groq()

    def status(ok: bool) -> str:
        return "operational" if ok else "degraded"

    agents_map = {
        "vision": "operational",       # local model inference, no external dependency
        "measurement": "operational",  # local OpenCV/ArUco, no external dependency
        "drawing": status(qdrant_ok),          # indexing writes to Qdrant
        "knowledge_graph": status(neo4j_ok),
        "compliance": status(pg_ok),
        "predictive_rfi": status(neo4j_ok and groq_ok),
        "memory": status(qdrant_ok),
        "version_control": status(neo4j_ok),
        "notification": status(pg_ok),
        "learning": status(pg_ok and qdrant_ok),
    }

    return {"agents": agents_map}


@router.get("/model-accuracy")
async def get_model_accuracy():
    """
    Reads the most recent models/evaluation/baseline_*.json produced by
    scripts/validate_baseline.py and returns real accuracy numbers — not a
    hardcoded figure. Powers the Executive Dashboard's "AI Accuracy Rate" KPI.
    """
    files = sorted(glob.glob(os.path.join(EVAL_DIR, "baseline_*.json")))
    if not files:
        return {"available": False}

    latest = files[-1]
    with open(latest) as f:
        report = json.load(f)

    tests = report.get("tests", {})
    accuracies = [t["accuracy"] for t in tests.values() if isinstance(t.get("accuracy"), (int, float))]
    overall = round((sum(accuracies) / len(accuracies)) * 100, 1) if accuracies else None

    return {
        "available": overall is not None,
        "overall_accuracy_pct": overall,
        "per_test": {k: v.get("accuracy") for k, v in tests.items()},
        "source_file": os.path.basename(latest),
        "timestamp": report.get("timestamp"),
    }
