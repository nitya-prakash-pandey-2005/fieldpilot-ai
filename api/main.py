from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from routes import knowledge_graph, drawing_intelligence, vision, measurement, compliance, predictive_rfi, memory, version_control, notification, learning, health, voice
import os

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up all models on server start
    from agents.version_control.scanner import VersionControlScanner
    VersionControlScanner.warmup()
    yield

app = FastAPI(title="ASK THE WALL API Gateway", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:8081").split(","),
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
app.include_router(voice.router, prefix="/api/v1/voice")

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
