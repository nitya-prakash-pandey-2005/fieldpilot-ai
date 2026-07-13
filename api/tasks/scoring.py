import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime

from db import async_session
from models.zones import Zone
from pubsub import bus

scheduler = AsyncIOScheduler()

import os

async def compute_zone_risks():
    if os.environ.get("DEMO_MODE", "false").lower() == "true":
        return
        
    print(f"[{datetime.utcnow().isoformat()}] Running zone risk scoring engine...")
    async with async_session() as session:
        result = await session.execute(select(Zone))
        zones = result.scalars().all()
        
        for zone in zones:
            # Inputs to weighted formula:
            # - open_issue_count         -> weight 0.35
            # - historical_rfi_density   -> weight 0.25 (Mocked to 2 for demo)
            # - active_worker_count      -> weight 0.20
            # - recent_incident_count    -> weight 0.20 (Mocked to 0 for demo)
            
            # Normalize inputs (mock normalization)
            norm_issues = min(zone.open_issue_count / 5.0, 1.0)
            norm_rfi = 2 / 10.0
            norm_workers = min(zone.active_worker_count / 30.0, 1.0)
            norm_incidents = 0
            
            # Additional random factor to simulate live changes in the dashboard
            import random
            flux = (random.random() * 0.1) - 0.05
            
            score_raw = (norm_issues * 0.35) + (norm_rfi * 0.25) + (norm_workers * 0.20) + (norm_incidents * 0.20) + flux
            score = int(max(0, min(100, score_raw * 100)))
            
            if score >= 70:
                risk_level = 'critical'
            elif score >= 40:
                risk_level = 'elevated'
            else:
                risk_level = 'normal'
                
            zone.risk_score = score
            zone.risk_level = risk_level
            zone.last_scored_at = datetime.utcnow()
            
            # Publish update to SSE clients
            await bus.publish(
                f"zone_updates:{zone.project_id}",
                {
                    "id": zone.id,
                    "risk_score": score,
                    "risk_level": risk_level,
                    "active_worker_count": zone.active_worker_count,
                    "open_issue_count": zone.open_issue_count,
                    "last_scored_at": zone.last_scored_at.isoformat() + "Z"
                }
            )
            
        await session.commit()

def start_scheduler():
    # Run every 30 seconds for the demo instead of 5 minutes so user sees live updates quickly
    scheduler.add_job(compute_zone_risks, 'interval', seconds=15)
    scheduler.start()
