import sys, os, asyncio
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
api_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(root_dir)
sys.path.append(api_dir)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from routes import knowledge_graph, drawing_intelligence, vision, measurement, compliance, predictive_rfi, memory, version_control, notification, learning, health, voice, zones, issues, planning, live_feed, auth, interactions, rfi_draft, localization
import os

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup Postgres tables (single unified DB/ORM — see models/zones.py's
    # shared Base; every model module must be imported here so its table
    # is registered on Base.metadata before create_all runs)
    from db import engine
    from models.zones import Base, Zone
    from models.issues import FieldIssue
    from models.project import Project, Asset
    from models.observation import Observation
    from models.compliance import ComplianceEvent
    from models.notification import NotificationAudit
    from models.resolved_incident import ResolvedIncident
    from models.user import User
    from models.interaction import Interaction
    from models.beacon import Beacon, WorkerPosition
    from sqlalchemy.ext.asyncio import AsyncSession

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed mock data if empty
    from db import async_session
    from sqlalchemy.future import select
    from datetime import datetime, timedelta
    from auth import hash_password
    async with async_session() as session:
        result_users = await session.execute(select(User))
        if len(result_users.scalars().all()) == 0:
            # One demo login per role — DEMO_PASSWORD is intentionally simple
            # and printed at startup; replace with real registration before
            # any non-demo deployment.
            demo_password_hash = hash_password("fieldpilot123")
            session.add_all([
                User(email="worker@fieldpilot.demo", password_hash=demo_password_hash, name="Ali Hassan", role="worker", zone_code="A12"),
                User(email="engineer@fieldpilot.demo", password_hash=demo_password_hash, name="Sarah Chen", role="engineer"),
                User(email="pm@fieldpilot.demo", password_hash=demo_password_hash, name="David Park", role="pm"),
                User(email="admin@fieldpilot.demo", password_hash=demo_password_hash, name="System Admin", role="admin"),
                User(email="executive@fieldpilot.demo", password_hash=demo_password_hash, name="Jordan Lee", role="executive"),
            ])
            await session.commit()
            print("[AUTH] Seeded 5 demo users (password: fieldpilot123) — worker/engineer/pm/admin/executive@fieldpilot.demo")

        result = await session.execute(select(Zone))
        if len(result.scalars().all()) == 0:
            session.add_all([
                Zone(id="z-1", project_id="default-project", zone_code="A12", name="Foundation Level 1 - North", current_activity="Rebar installation", active_worker_count=14, open_issue_count=2, risk_level="critical", risk_score=85),
                Zone(id="z-2", project_id="default-project", zone_code="B3", name="Podium Level 3 - East", current_activity="MEP rough-in", active_worker_count=8, open_issue_count=2, risk_level="elevated", risk_score=45),
                Zone(id="z-3", project_id="default-project", zone_code="C7", name="Tower Floor 12 - Core", current_activity="Concrete curing", active_worker_count=22, open_issue_count=1, risk_level="normal", risk_score=12)
            ])
            await session.commit()
            
        result_issues = await session.execute(select(FieldIssue))
        if len(result_issues.scalars().all()) == 0:
            now = datetime.utcnow()
            session.add_all([
                FieldIssue(id="issue-1", project_id="default-project", zone_id="z-1", zone_code="A12", issue_type="Rebar Grid", severity="critical", description="Rebar spacing is 190mm. Specification requires 150mm ±10mm. Deviation is 40mm above maximum. STOP WORK.", deviation_pct=26.6, measured_value="190mm", expected_value="150mm", worker_id="W-022", created_at=now - timedelta(hours=3)),
                FieldIssue(id="issue-2", project_id="default-project", zone_id="z-2", zone_code="B3", issue_type="Conduit Routing", severity="high", description="Worker using outdated drawing S-101-R3. Latest approved is R5 (Nov 2, 2024). R5 changes conduit routing in this zone.", deviation_pct=12.0, measured_value="Drawing R3", expected_value="Drawing R5", worker_id="W-015", created_at=now - timedelta(hours=3, minutes=6)),
                FieldIssue(id="issue-3", project_id="default-project", zone_id="z-3", zone_code="C7", issue_type="HVAC Duct", severity="medium", description="Clearance height is 2.85m. Minimum clearance per spec is 3.00m. Warning generated.", deviation_pct=8.5, measured_value="2.85m", expected_value="3.00m", worker_id="W-088", created_at=now - timedelta(hours=3, minutes=43)),
                FieldIssue(id="issue-4", project_id="default-project", zone_id="z-1", zone_code="A12", issue_type="Concrete Formwork", severity="high", description="Formwork is leaning by 2.3 degrees. Maximum allowable tolerance is 1.0 degree.", deviation_pct=15.0, measured_value="2.3 deg", expected_value="0 deg", worker_id="W-842", created_at=now - timedelta(hours=4, minutes=58)),
                FieldIssue(id="issue-5", project_id="default-project", zone_id="z-2", zone_code="B3", issue_type="Cable Tray", severity="medium", description="Cable tray offset is 520mm from wall, expected 550mm.", deviation_pct=5.5, measured_value="520mm", expected_value="550mm", worker_id="W-015", created_at=now - timedelta(hours=5, minutes=58))
            ])
            await session.commit()
            
    # Start Scheduler
    from tasks.scoring import start_scheduler
    start_scheduler()

    # Warm up all models on server start
    from agents.version_control.scanner import VersionControlScanner
    VersionControlScanner.warmup()
    yield

app = FastAPI(title="FieldPilot AI API Gateway", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://localhost:8081,https://fieldpilot-ai-ovzd.vercel.app").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(knowledge_graph.router)
app.include_router(drawing_intelligence.router)
app.include_router(vision.router)
app.include_router(measurement.router)
app.include_router(compliance.router)
app.include_router(predictive_rfi.router)
app.include_router(memory.router)
app.include_router(version_control.router)
app.include_router(notification.router)
app.include_router(learning.router)
app.include_router(health.router)
app.include_router(voice.router)
app.include_router(zones.router)
app.include_router(issues.router)
app.include_router(planning.router)
app.include_router(live_feed.router)
app.include_router(interactions.router)
app.include_router(rfi_draft.router)
app.include_router(localization.router)

from datetime import datetime

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "0.1.0"
    }

from fastapi.responses import Response

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(content=b"", media_type="image/x-icon")

connected_clients: dict[str, list[WebSocket]] = {}

@app.websocket("/ws/twin/{project_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    project_id: str
):
    await websocket.accept()
    
    if project_id not in connected_clients:
        connected_clients[project_id] = []
    connected_clients[project_id].append(websocket)
    
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_clients.get(project_id, []):
            connected_clients[project_id].remove(websocket)

async def broadcast_event(
    project_id: str,
    event: dict
):
    if project_id in connected_clients:
        dead = []
        for client in connected_clients[project_id]:
            try:
                await client.send_json(event)
            except:
                dead.append(client)
        for d in dead:
            if d in connected_clients[project_id]:
                connected_clients[project_id].remove(d)


# ---------------------------------------------------------------------------
# Zone-scoped cross-worker hazard advisory — Phase 2 Day 11 item. Previously
# there was no zone-scoped broadcast anywhere: broadcast_event() above is
# project-wide (and unconsumed by any current frontend page), so a hazard
# detected by one worker had no way to advise OTHER workers physically
# present in the SAME zone, while correctly staying silent for workers in a
# different zone. Any session (worker glasses feed, dashboard, a second
# browser tab) can subscribe to a zone channel; ComplianceEngine.validate()
# publishes here for HIGH/CRITICAL results.
# ---------------------------------------------------------------------------
zone_listeners: dict[str, list[WebSocket]] = {}

@app.websocket("/ws/zone/{zone_code}")
async def zone_advisory_ws(websocket: WebSocket, zone_code: str):
    await websocket.accept()
    zone_listeners.setdefault(zone_code, []).append(websocket)
    try:
        while True:
            await asyncio.sleep(1)  # keep-alive; advisories arrive via broadcast_zone_advisory
    except WebSocketDisconnect:
        if websocket in zone_listeners.get(zone_code, []):
            zone_listeners[zone_code].remove(websocket)


async def broadcast_zone_advisory(zone_code: str, event: dict):
    """Sends `event` to every session subscribed to this zone's channel only
    — a worker subscribed to a different zone never receives it, which is
    the actual acceptance criterion (same zone gets advisory, different
    zone doesn't), not just a single global broadcast."""
    dead = []
    for ws in zone_listeners.get(zone_code, []):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        listeners = zone_listeners.get(zone_code, [])
        if ws in listeners:
            listeners.remove(ws)

from pydantic import BaseModel

glasses_listeners: dict[str, WebSocket] = {}

@app.websocket("/ws/glasses/{worker_id}")
async def glasses_ws(websocket: WebSocket, worker_id: str):
    await websocket.accept()
    
    # Register this dashboard as listener
    glasses_listeners[worker_id] = websocket
    
    try:
        while True:
            await asyncio.sleep(1)  # Keep alive
    except WebSocketDisconnect:
        glasses_listeners.pop(worker_id, None)

class GlassesFramePayload(BaseModel):
    frame: str
    worker_id: str
    zone_id: str = "A12"
    language: str = "EN"

_URGENCY_TO_VERDICT = {"critical": "CRITICAL", "high": "HIGH", "medium": "WARNING", "low": "PASS"}


@app.post("/api/v1/glasses/frame")
async def receive_glasses_frame(payload: GlassesFramePayload):
    """
    Real scene analysis for the "Meta Glasses" WS mode — previously this
    returned the exact same hardcoded "UNCERTAIN / 85%" result regardless
    of the frame sent. Reuses the same VLMAnalyzer instance as
    POST /api/v1/vision/understand (routes/vision.py) so a model isn't
    loaded twice.
    """
    import time as _time
    from routes.vision import vlm_analyzer as _vlm

    start = _time.time()
    try:
        scene = await _vlm.analyze_scene(
            image_base64=payload.frame.split(",")[-1] if "," in payload.frame else payload.frame,
            zone_id=payload.zone_id,
            language=payload.language.lower()[:2] if payload.language else "en",
        )
    except Exception as e:
        scene = {"scene_description": f"Analysis error: {e}", "urgency": "low",
                  "safety_hazards": [], "compliance_issues": [], "confidence": 0.0}

    urgency = (scene.get("urgency") or "low").lower()
    hazards = scene.get("safety_hazards") or []
    compliance_issues = scene.get("compliance_issues") or []
    issue_count = len(hazards) + len(compliance_issues)
    confidence = scene.get("confidence")

    result = {
        "name": scene.get("work_type") or "Live Scene Analysis",
        "image": "",
        "verdict": _URGENCY_TO_VERDICT.get(urgency, "PASS"),
        "issue": (compliance_issues[0] if compliance_issues else hazards[0] if hazards else scene.get("work_type") or "Scene analyzed"),
        "measured": scene.get("scene_description") or "No description returned",
        "required": "Per project specification" if compliance_issues else "N/A",
        "deviation": f"{issue_count} issue(s) flagged" if issue_count else "N/A",
        "confidence": f"{round(confidence * 100)}%" if isinstance(confidence, (int, float)) else "N/A",
        "agentChain": "V1→VLM(Groq)",
        "time": f"{_time.time() - start:.1f}s",
    }

    # Broadcast to dashboard
    if payload.worker_id in glasses_listeners:
        await glasses_listeners[payload.worker_id].send_json({
            "type": "analysis_result",
            "result": result,
            "frame": payload.frame,
            "fps": 2.0,
            "latency": round((_time.time() - start) * 1000),
        })

    return result

# ---------------------------------------------------------------------------
# Live camera WebSocket — streams real-time annotated frames to the frontend
# ---------------------------------------------------------------------------

live_listeners: dict[str, list[WebSocket]] = {}

@app.websocket("/ws/live/{worker_id}")
async def live_ws_endpoint(websocket: WebSocket, worker_id: str):
    """
    Frontend LiveCameraPanel connects here.
    The live_camera_pipeline.py script posts frames via REST;
    this endpoint pushes those frames to the browser.
    """
    await websocket.accept()
    if worker_id not in live_listeners:
        live_listeners[worker_id] = []
    live_listeners[worker_id].append(websocket)
    print(f"[WS/live] Browser connected for worker {worker_id}")
    try:
        while True:
            await asyncio.sleep(1)   # keep-alive; frames arrive via broadcast
    except WebSocketDisconnect:
        if websocket in live_listeners.get(worker_id, []):
            live_listeners[worker_id].remove(websocket)
        print(f"[WS/live] Browser disconnected for worker {worker_id}")


async def broadcast_live_frame(worker_id: str, payload: dict):
    """Called by live_feed route to push frame data to all listening browsers."""
    dead = []
    for ws in live_listeners.get(worker_id, []):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        listeners = live_listeners.get(worker_id, [])
        if ws in listeners:
            listeners.remove(ws)


# Trigger reload for DEMO_MODE
