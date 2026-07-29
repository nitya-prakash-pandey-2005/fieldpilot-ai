"""
Offline Store-and-Forward Queue — FieldPilot AI
--------------------------------------------------
Local SQLite-backed spool so hazard/frame events detected on the edge
device survive a real network outage instead of being silently dropped.
Previously, both live_camera_pipeline.py's post_frame_async() and
glasses_simulator.py's frame POST used a bare `except Exception: pass` on
failure — losing the event entirely with no way to recover it once
connectivity returned. This is genuine local persistence (a file on disk,
not an in-memory queue), so it also survives the edge process itself
restarting mid-outage.

Day 4 test: disable WiFi mid-run, confirm events accumulate in the local
spool (pending_count() > 0), restore WiFi, confirm they drain and reach
the API (pending_count() returns to 0).

Usage:
    queue = OfflineQueue()
    queue.send_or_queue(f"{api_url}/api/v1/live/frame", payload)
"""

import os
import json
import sqlite3
import threading
import time
import requests

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "offline_queue.db"
)
DRAIN_INTERVAL_SEC = 3.0
DRAIN_BATCH_SIZE = 20


class OfflineQueue:
    """
    One instance per edge process. send_or_queue() tries a real send first
    (no needless local write + latency in the common online case) and only
    spools locally on failure. A background thread periodically drains
    anything queued, oldest first, once connectivity returns.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self._running = True
        self._drain_thread = threading.Thread(
            target=self._drain_loop, daemon=True, name="offline-queue-drain"
        )
        self._drain_thread.start()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    def _init_db(self):
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queued_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    queued_at REAL NOT NULL,
                    attempts INTEGER DEFAULT 0
                )
            """)

    def send_or_queue(self, url: str, payload: dict, timeout: float = 3.0) -> bool:
        """Try a real send now; spool locally only if it fails. Returns True if sent live."""
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return True
        except Exception:
            self._enqueue(url, payload)
            return False

    def _enqueue(self, url: str, payload: dict):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO queued_events (url, payload, queued_at) VALUES (?, ?, ?)",
                (url, json.dumps(payload), time.time()),
            )

    def pending_count(self) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM queued_events").fetchone()[0]

    def _drain_loop(self):
        while self._running:
            time.sleep(DRAIN_INTERVAL_SEC)
            self._drain_once()

    def _drain_once(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, url, payload FROM queued_events ORDER BY id ASC LIMIT ?",
                (DRAIN_BATCH_SIZE,),
            ).fetchall()
        if not rows:
            return
        for row_id, url, payload_json in rows:
            try:
                resp = requests.post(url, json=json.loads(payload_json), timeout=3)
                resp.raise_for_status()
                with self._lock, self._connect() as conn:
                    conn.execute("DELETE FROM queued_events WHERE id = ?", (row_id,))
            except Exception:
                # Still offline (or backend down) — stop draining this round
                # rather than burning through the whole backlog against a
                # dead connection; the next interval will retry from here.
                with self._lock, self._connect() as conn:
                    conn.execute(
                        "UPDATE queued_events SET attempts = attempts + 1 WHERE id = ?", (row_id,)
                    )
                break

    def stop(self):
        self._running = False
