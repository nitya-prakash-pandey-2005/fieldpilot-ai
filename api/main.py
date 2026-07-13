import sys, os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from routes import knowledge_graph, drawing_intelligence, vision, measurement, compliance, predictive_rfi, memory, version_control, notification, learning, health, voice, zones, issues, planning
import os

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup SQLite tables
    from db import engine
    from models.zones import Base, Zone
    from sqlalchemy.ext.asyncio import AsyncSession
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # Seed mock data if empty
    from db import async_session
    from sqlalchemy.future import select
    from models.issues import FieldIssue
    from datetime import datetime, timedelta
    async with async_session() as session:
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

from datetime import datetime

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "0.1.0"
    }

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

import asyncio
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

@app.post("/api/v1/glasses/frame")
async def receive_glasses_frame(payload: GlassesFramePayload):
    # Mock VLM analysis for demo
    result = {
          "name": "Custom Scene Analysis",
          "image": "",
          "verdict": "UNCERTAIN",
          "issue": "Unknown Scene",
          "measured": "Manual review required",
          "required": "N/A",
          "deviation": "N/A",
          "confidence": "85%",
          "agentChain": "V1",
          "time": "1.2s"
    }
    
    # Broadcast to dashboard
    if payload.worker_id in glasses_listeners:
        await glasses_listeners[payload.worker_id].send_json({
            "type": "analysis_result",
            "result": result,
            "frame": payload.frame,
            "fps": 2.0,
            "latency": 45
        })
    
    return result

# Trigger reload for DEMO_MODE
