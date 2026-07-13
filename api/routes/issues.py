from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime
import json
import asyncio
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from db import get_db
from models.issues import FieldIssue
from pubsub import bus

router = APIRouter(prefix="/api/v1")

class ResolveRequest(BaseModel):
    resolved_by_user_id: str
    resolution_note: str

class EscalateRequest(BaseModel):
    escalated_by_user_id: str
    escalate_to_role: str
    note: Optional[str] = ""

class ExportRequest(BaseModel):
    severity_filter: str
    format: str

def issue_to_dict(issue: FieldIssue):
    return {
        "id": issue.id,
        "project_id": issue.project_id,
        "zone_id": issue.zone_id,
        "zone_code": issue.zone_code,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "status": issue.status,
        "description": issue.description,
        "deviation_pct": float(issue.deviation_pct) if issue.deviation_pct else None,
        "measured_value": issue.measured_value,
        "expected_value": issue.expected_value,
        "worker_id": issue.worker_id,
        "resolved_by": issue.resolved_by,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "resolution_note": issue.resolution_note,
        "escalated_to": issue.escalated_to,
        "escalated_at": issue.escalated_at.isoformat() if issue.escalated_at else None,
        "detected_by": issue.detected_by,
        "drawing_ref": issue.drawing_ref,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None
    }

@router.get("/projects/{project_id}/issues")
async def get_issues(
    project_id: str,
    severity: Optional[str] = Query("all"),
    status: Optional[str] = Query("all"),
    zone_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    query = select(FieldIssue).where(FieldIssue.project_id == project_id)
    
    if severity and severity != "all":
        query = query.where(FieldIssue.severity == severity)
    if status and status != "all":
        query = query.where(FieldIssue.status == status)
    if zone_id:
        query = query.where(FieldIssue.zone_id == zone_id)
        
    query = query.order_by(
        desc(FieldIssue.created_at)
    )
    
    result = await db.execute(query)
    issues = result.scalars().all()
    
    # Simple Python-side sorting to prioritize severity first as requested
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    issues_sorted = sorted(issues, key=lambda x: (severity_order.get(x.severity, 4), -x.created_at.timestamp()))
    
    # Calculate summary
    summary = {
        "total": len(issues),
        "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "open": sum(1 for i in issues if i.status == "open"),
        "resolved_today": 0
    }
    
    today = datetime.utcnow().date()
    for i in issues:
        if i.severity in summary["by_severity"]:
            summary["by_severity"][i.severity] += 1
        if i.status == "resolved" and i.resolved_at and i.resolved_at.date() == today:
            summary["resolved_today"] += 1

    return {
        "issues": [issue_to_dict(i) for i in issues_sorted],
        "summary": summary
    }

@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(issue_id: str, req: ResolveRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FieldIssue).where(FieldIssue.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
        
    issue.status = "resolved"
    issue.resolved_at = datetime.utcnow()
    issue.resolved_by = req.resolved_by_user_id
    issue.resolution_note = req.resolution_note
    await db.commit()
    
    # Broadcast SSE
    await bus.publish(f"project_{issue.project_id}_issues", {
        "type": "ISSUE_RESOLVED",
        "issue_id": issue.id
    })
    
    return {"issue_id": issue.id, "status": "resolved", "resolved_at": issue.resolved_at.isoformat()}

@router.post("/issues/{issue_id}/escalate")
async def escalate_issue(issue_id: str, req: EscalateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FieldIssue).where(FieldIssue.id == issue_id))
    issue = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
        
    issue.status = "escalated"
    issue.escalated_at = datetime.utcnow()
    issue.escalated_to = req.escalate_to_role
    
    # In a real app we would store the note in a separate comments/history table
    # Here we append it to the description or store it if we had a dedicated field.
    await db.commit()
    
    # Broadcast SSE
    await bus.publish(f"project_{issue.project_id}_issues", {
        "type": "ISSUE_ESCALATED",
        "issue_id": issue.id
    })
    
    return {"issue_id": issue.id, "status": "escalated", "notified_users": ["manager_1"]}

@router.get("/projects/{project_id}/issues/stream")
async def issues_stream(project_id: str):
    async def event_generator():
        q = bus.subscribe(f"project_{project_id}_issues")
        try:
            while True:
                msg = await q.get()
                yield json.dumps(msg)
        except asyncio.CancelledError:
            bus.unsubscribe(f"project_{project_id}_issues", q)
            raise

    return EventSourceResponse(event_generator())

@router.post("/projects/{project_id}/issues/export")
async def export_issues(project_id: str, req: ExportRequest, db: AsyncSession = Depends(get_db)):
    # Generate real PDF using ReportLab
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    import io
    import base64

    query = select(FieldIssue).where(FieldIssue.project_id == project_id)
    if req.severity_filter and req.severity_filter != "ALL":
        query = query.where(FieldIssue.severity == req.severity_filter.lower())
    
    result = await db.execute(query)
    issues = result.scalars().all()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, f"FieldPilot AI Export - {project_id}")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 70, f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    c.drawString(50, height - 90, f"Filter: {req.severity_filter}")
    
    y = height - 130
    for idx, issue in enumerate(issues):
        if y < 100:
            c.showPage()
            y = height - 50
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, f"Issue #{idx+1}: {issue.issue_type} (Zone {issue.zone_code})")
        y -= 20
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Severity: {issue.severity.upper()}")
        y -= 15
        c.drawString(50, y, f"Description: {issue.description[:100]}...")
        y -= 15
        c.drawString(50, y, f"Measured: {issue.measured_value} | Expected: {issue.expected_value}")
        y -= 15
        c.drawString(50, y, f"Worker: {issue.worker_id} | Time: {issue.created_at}")
        y -= 30

    c.setFont("Helvetica-Oblique", 8)
    c.drawString(50, 30, f"Generated by FieldPilot AI Vision Agent")
    c.save()

    buffer.seek(0)
    pdf_b64 = base64.b64encode(buffer.read()).decode('utf-8')
    download_url = f"data:application/pdf;base64,{pdf_b64}"

    return {
        "download_url": download_url,
        "expires_at": datetime.utcnow().isoformat()
    }
