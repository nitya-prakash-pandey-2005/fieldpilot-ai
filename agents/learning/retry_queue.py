import os
import json
import logging
from datetime import datetime
import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis connection
redis_client = None

def get_redis():
    global redis_client
    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url, decode_responses=True)
    return redis_client

async def queue_failed_write(backend: str, incident_id: str, payload: dict):
    """
    Pushes a failed write payload to the Redis retry queue.
    backend: e.g. 'neo4j', 'qdrant'
    """
    try:
        r = get_redis()
        queue_name = f"retry:{backend}"
        
        item = {
            "incident_id": incident_id,
            "payload": payload,
            "failed_at": datetime.utcnow().isoformat(),
            "attempts": 0
        }
        
        await r.lpush(queue_name, json.dumps(item))
        logger.info(f"Queued failed {backend} write for incident {incident_id}")
    except Exception as e:
        logger.error(f"Failed to push to Redis retry queue for {backend}: {e}")
