"""
FieldPilot AI — Live Camera Pipeline (v2 — Fixed Lag + Voice)
================================================================
Fixes v1 issues:
  1. VIDEO LAG — dedicated frame-grabber thread discards buffered frames,
     always presents the LATEST frame. ML runs in parallel without blocking.
  2. VOICE SPAM — zone-level consolidated alerts instead of per-worker.
     "3 workers missing PPE in Zone A12" fires once per throttle window,
     not one alert per track-ID per frame. Falls still per-worker.

Sources:
  1. Laptop webcam (default)
  2. Phone camera  — IP Webcam Android app (http://PHONE_IP:8080/video)
  3. Video file    — data/sample_construction.mp4

HOW TO FIND YOUR PHONE IP:
  python scripts/live_camera_pipeline.py --how-to-find-ip

Usage:
  python scripts/live_camera_pipeline.py                              # laptop
  python scripts/live_camera_pipeline.py --source phone --phone-ip 192.168.1.42
  python scripts/live_camera_pipeline.py --source video
  python scripts/live_camera_pipeline.py --no-stream                  # standalone
  python scripts/live_camera_pipeline.py --mute                       # no voice
"""

import sys
import os
import time
import base64
import threading
import argparse
import json
import queue
import cv2
import numpy as np
import requests
import asyncio
import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents.vision.detector import VisionPipeline
from agents.voice.earcons import play_earcon, HazardCategory
from scripts.offline_queue import OfflineQueue

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_API     = "http://localhost:8000"
DEFAULT_ZONE    = "A12"
DEFAULT_WORKER  = "WRK-001"
PHONE_PORT      = 8080
JPEG_QUALITY    = 55

VIDEO_PATH = os.path.join(ROOT, "data", "sample_construction.mp4")

# How often (seconds) between ML inference runs — tuned for no lag
ML_INTERVAL_SEC = 0.5   # run inference at most twice per second

# ---------------------------------------------------------------------------
# Voice Alerter — CONTINUOUS mode (speaks without stopping while violations exist)
# ---------------------------------------------------------------------------

class VoiceAlerter:
    """
    Continuous TTS alert system.

    Architecture:
      - ML thread calls update_state(result) after every inference.
      - A single background speaker thread reads the current state,
        builds an alert sentence, speaks it to completion, then
        immediately speaks it again — until violations clear.
      - Falls get highest priority and interrupt any ongoing PPE speech.
      - Press M at runtime to toggle mute.
    """

    def __init__(self, muted: bool = False):
        self.muted    = muted
        self._engine  = None
        self._lock    = threading.Lock()
        # Current violation state (updated by ML every 0.5s)
        self._falls:        list[str] = []     # list of fallen worker IDs
        self._struck_by:    list[str] = []     # worker IDs near heavy equipment
        self._n_ppe:        int = 0            # number of PPE violators
        self._ppe_items:    list[str] = []     # unique missing items
        self._escalated:    int = 0            # workers with ESCALATED attention state
        self._risk_level:   str = "normal"
        self._zone_id:      str = "A12"
        self._running = True
        if not muted:
            self._init_engine()

    def _init_engine(self):
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.setProperty("rate",   155)     # slightly slower = clearer
            eng.setProperty("volume", 1.0)
            for v in eng.getProperty("voices") or []:
                name = (v.name or "").lower()
                if any(x in name for x in ("zira", "david", "english", "hazel")):
                    eng.setProperty("voice", v.id)
                    break
            self._engine = eng
            print(f"[VOICE] TTS ready — continuous mode — {eng.getProperty('voice')}")
            threading.Thread(target=self._continuous_loop, daemon=True, name="tts").start()
        except Exception as e:
            print(f"[VOICE] TTS unavailable: {e}. Run: pip install pyttsx3")
            self._engine = None

    def _build_alert_text(self) -> tuple[str, "HazardCategory"] | tuple[None, None]:
        """
        Build the single alert sentence for the CURRENT state, plus the
        earcon category to play immediately before it — the category
        matches whichever condition actually drove the sentence (highest
        priority first), so the audio cue and the words are always about
        the same hazard. Returns (None, None) if everything is safe.
        Priority: falls > struck-by > PPE > escalated attention > zone risk.
        """
        with self._lock:
            falls      = list(self._falls)
            struck_by  = list(self._struck_by)
            n_ppe      = self._n_ppe
            ppe_items  = list(dict.fromkeys(self._ppe_items[:4]))  # deduplicate
            escalated  = self._escalated
            risk       = self._risk_level
            zone       = self._zone_id

        if falls:
            who = " and ".join(falls[:2])  # max 2 names to keep it short
            return (f"Warning! Worker {who} has fallen in Zone {zone}. Respond immediately.", HazardCategory.FALL)

        if struck_by:
            who = " and ".join(struck_by[:2])
            return (f"Danger! Worker {who} is too close to heavy equipment in Zone {zone}. Move back.", HazardCategory.STRUCK_BY)

        if n_ppe > 0:
            items_str = ", ".join(ppe_items) if ppe_items else "safety equipment"
            who = "1 worker is" if n_ppe == 1 else f"{n_ppe} workers are"
            return (f"Safety alert! {who} missing {items_str} in Zone {zone}.", HazardCategory.PPE_VIOLATION)

        if escalated > 0:
            who = "1 worker has" if escalated == 1 else f"{escalated} workers have"
            return (f"Reminder! {who} not acknowledged a flagged hazard in Zone {zone}.", HazardCategory.ESCALATED_ATTENTION)

        if risk in ("high", "critical"):
            if risk == "critical":
                return (f"Critical risk in Zone {zone}. Supervisor required immediately.", HazardCategory.PPE_VIOLATION)
            return (f"High risk in Zone {zone}. Check for safety violations.", HazardCategory.PPE_VIOLATION)

        return (None, None)

    def _continuous_loop(self):
        """
        Speaks the current alert on repeat, without stopping,
        as long as violations are detected.
        Between utterances: 0.3s pause (barely noticeable — keeps it continuous).
        """
        while self._running:
            if self.muted:
                time.sleep(0.2)
                continue

            text, category = self._build_alert_text()

            if text and self._engine:
                print(f"[VOICE] >> ({category.value}) {text}")
                play_earcon(category)  # short distinct cue before the spoken alert
                try:
                    self._engine.say(text)
                    self._engine.runAndWait()
                except Exception:
                    pass
                time.sleep(0.3)   # tiny gap between repetitions
            else:
                # Nothing to say — check again shortly
                time.sleep(0.4)

    # ── Called by ML thread ─────────────────────────────────────────────

    def update_state(self, result: dict, zone_id: str):
        """
        Update current violation state from latest ML result.
        Called after every inference — the continuous_loop picks it up.
        """
        zone   = result.get("zone_summary", {})
        risk   = zone.get("zone_risk_level", "normal")
        falls  = list(result.get("fall_events", []))
        struck_by = list(result.get("struck_by_events", []))

        n_ppe     = 0
        ppe_items = []
        escalated = 0
        for check in result.get("compliance_checks", []):
            violations = [item for item in ["hardhat", "vest", "gloves", "glasses", "boots"]
                          if check.get(item) is False]
            if violations:
                n_ppe += 1
                ppe_items.extend(violations)
            if check.get("attention_state") == "ESCALATED":
                escalated += 1

        with self._lock:
            self._falls      = falls
            self._struck_by  = struck_by
            self._n_ppe      = n_ppe
            self._ppe_items  = ppe_items
            self._escalated  = escalated
            self._risk_level = risk
            self._zone_id    = zone_id

    def startup(self, zone_id: str):
        """Speak once at startup."""
        if self._engine and not self.muted:
            try:
                self._engine.say(f"FieldPilot AI active. Monitoring Zone {zone_id}.")
                self._engine.runAndWait()
            except Exception:
                pass
        print(f"[VOICE] Monitoring Zone {zone_id}")



# ---------------------------------------------------------------------------
# Frame Grabber Thread — eliminates lag
# ---------------------------------------------------------------------------

class FrameGrabber:
    """
    Continuously reads frames from the camera in a background thread.
    Only keeps the LATEST frame — discards buffered stale frames.
    This is the key fix for the lag problem.
    """

    def __init__(self, cap: cv2.VideoCapture, source: str = "laptop"):
        self._cap    = cap
        self._source = source
        self._frame  = None
        self._lock   = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name="frame-grab")
        self._thread.start()

    def _grab_loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                if self._source == "video":
                    # Loop video
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.01)
                continue
            with self._lock:
                self._frame = frame
            # Small sleep only for video files to simulate real-time fps
            if self._source == "video":
                time.sleep(1 / 30)

    def get_latest(self):
        """Get the most recent frame (non-blocking)."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# WebSocket streamer
# ---------------------------------------------------------------------------

class WebSocketStreamer:
    def __init__(self, api_url: str, worker_id: str):
        self.ws_url = (api_url.replace("http://", "ws://")
                               .replace("https://", "wss://")
                       + f"/ws/live/{worker_id}")
        self._q       = asyncio.Queue(maxsize=3)
        self._loop    = None
        self._attempts = 0

    def start(self):
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_ws())
        threading.Thread(target=_run, daemon=True, name="ws").start()

    def send(self, payload: dict):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._enqueue(payload), self._loop)

    async def _enqueue(self, p):
        try:
            self._q.put_nowait(p)
        except asyncio.QueueFull:
            pass

    async def _run_ws(self):
        while True:
            try:
                async with websockets.connect(self.ws_url,
                                              ping_interval=20, close_timeout=5) as ws:
                    self._attempts = 0
                    print(f"[WS] Connected to {self.ws_url}")
                    while True:
                        payload = await self._q.get()
                        await ws.send(json.dumps(payload))
            except Exception:
                self._attempts += 1
                if self._attempts <= 2:
                    print("[WS] Backend not reachable — running standalone")
                await asyncio.sleep(min(2 ** min(self._attempts, 4), 30))


_offline_queue = OfflineQueue()


def post_frame_async(api_url, worker_id, zone_id, frame_b64, detections):
    """
    Post the current hazard/frame event, spooling it locally instead of
    silently dropping it if the network is down (Day 4 offline
    store-and-forward — previously a bare `except Exception: pass` here
    meant an outage lost every event for its duration).
    """
    def _post():
        _offline_queue.send_or_queue(
            f"{api_url}/api/v1/live/frame",
            {"worker_id": worker_id, "zone_id": zone_id,
             "frame": frame_b64,
             "detections": {k: v for k, v in detections.items()
                            if k != "annotated_frame"}},
        )
    threading.Thread(target=_post, daemon=True).start()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def encode_frame(frame, quality=JPEG_QUALITY):
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode()


def print_phone_ip_guide():
    print("""
+------------------------------------------------------------------+
|  HOW TO FIND YOUR PHONE IP ADDRESS                               |
+------------------------------------------------------------------+
|  ANDROID (IP Webcam app):                                        |
|    1. Install "IP Webcam" from Google Play Store (free)          |
|    2. Open app, scroll to bottom, tap "Start server"             |
|    3. IP shown on screen: e.g.  http://192.168.1.42:8080         |
|    4. Run:                                                        |
|       python scripts/live_camera_pipeline.py \\                   |
|              --source phone --phone-ip 192.168.1.42              |
|  ANDROID (manual): Settings > WiFi > tap network > IP Address    |
|  iOS (EpocCam): Settings > WiFi > tap (i) > IP Address          |
|  IMPORTANT: Phone & laptop must be on the SAME WiFi network!     |
+------------------------------------------------------------------+
""")


def find_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def decode_source(args):
    if args.source == "phone":
        if args.phone_ip in ("YOUR_PHONE_IP", "", "192.168.1.100"):
            print_phone_ip_guide()
            print("ERROR: Provide your phone IP with --phone-ip YOUR_IP")
            sys.exit(1)
        ip, port = args.phone_ip, args.phone_port
        print(f"\nConnecting to phone at {ip}:{port}...")
        for url in [f"http://{ip}:{port}/video", f"http://{ip}:{port}/videofeed"]:
            cap = cv2.VideoCapture(url)
            if cap.isOpened():
                print(f"  Connected! ({url})")
                return cap
        print("Could not connect to phone.")
        print_phone_ip_guide()
        sys.exit(1)

    elif args.source == "video":
        if not os.path.exists(VIDEO_PATH):
            print(f"ERROR: Video not found: {VIDEO_PATH}")
            sys.exit(1)
        print(f"Opening video: {VIDEO_PATH}")
        cap = cv2.VideoCapture(VIDEO_PATH)
    else:
        print(f"Opening laptop webcam (index {args.cam_index})")
        cap = cv2.VideoCapture(args.cam_index, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(args):
    if getattr(args, "how_to_find_ip", False):
        print_phone_ip_guide()
        print(f"  Your laptop's local IP: {find_local_ip()}")
        return

    RISK_COLORS = {
        "critical": (0, 0, 255),
        "high"    : (0, 80, 255),
        "elevated": (0, 165, 255),
        "normal"  : (0, 200, 80),
    }

    print("\n" + "="*62)
    print("  FIELDPILOT AI  |  Live Camera Pipeline v2")
    print("="*62)
    print(f"  Source  : {args.source}" +
          (f"  ({args.phone_ip}:{args.phone_port})" if args.source == "phone" else ""))
    print(f"  Zone    : {args.zone}  |  Worker: {args.worker}")
    print(f"  Voice   : {'MUTED' if args.mute else 'ON — continuous, speaks non-stop while violations detected'}")
    print(f"  Stream  : {'DISABLED (standalone)' if args.no_stream else args.api}")
    print("="*62 + "\n")

    # ── Voice ────────────────────────────────────────────────────────────
    voice = VoiceAlerter(muted=args.mute)

    # ── ML Pipeline ─────────────────────────────────────────────────────
    print("[ML] Loading Tier 1 pipeline...")
    pipeline = VisionPipeline(zone_id=args.zone)
    print("[ML] Ready.\n")

    # ── Camera ──────────────────────────────────────────────────────────
    cap = decode_source(args)
    if not cap.isOpened():
        print("ERROR: Could not open video source.")
        sys.exit(1)

    # ── Frame grabber thread (fixes lag) ─────────────────────────────────
    grabber = FrameGrabber(cap, args.source)
    # Wait for first frame
    for _ in range(50):
        if grabber.get_latest() is not None:
            break
        time.sleep(0.05)

    # ── WS streamer ──────────────────────────────────────────────────────
    ws_streamer = None
    if not args.no_stream:
        ws_streamer = WebSocketStreamer(args.api, args.worker)
        ws_streamer.start()

    # Delayed startup voice (after models loaded)
    threading.Timer(1.0, lambda: voice.startup(args.zone)).start()

    # ── State ────────────────────────────────────────────────────────────
    last_result   = {}
    last_ml_time  = 0.0           # time of last ML inference
    ml_running    = threading.Event()
    display_frame = None          # latest annotated frame for display
    display_lock  = threading.Lock()

    fps_times: list[float] = []

    show_window = not args.headless
    print("LIVE  |  Q=quit  S=snapshot  M=mute toggle")

    # ── ML worker (runs inference asynchronously) ─────────────────────
    def _run_ml(f, wid, zid):
        nonlocal last_result
        result  = pipeline.analyze_frame(f)
        last_result = result

        ann = result.get("annotated_frame")
        with display_lock:
            nonlocal display_frame
            display_frame = (ann if ann is not None else f).copy()

        voice.update_state(result, zid)

        if ws_streamer:
            b64     = encode_frame(ann if ann is not None else f)
            payload = {
                "type"      : "live_frame",
                "worker_id" : wid, "zone_id": zid,
                "frame"     : b64,
                "detections": {
                    "zone_summary": result.get("zone_summary", {}),
                    "fall_events" : result.get("fall_events", []),
                    "compliance"  : result.get("compliance_checks", []),
                },
                "timestamp" : time.time(),
            }
            ws_streamer.send(payload)
            if not args.no_stream:
                post_frame_async(args.api, wid, zid, b64, result)

        ml_running.clear()

    # ── Display loop — runs at full camera FPS, never blocked by ML ────
    while True:
        now = time.time()

        # Get latest camera frame (instant, no blocking)
        latest_raw = grabber.get_latest()
        if latest_raw is None:
            time.sleep(0.01)
            continue

        # Trigger ML inference if due and not already running
        if not ml_running.is_set() and (now - last_ml_time) >= ML_INTERVAL_SEC:
            last_ml_time = now
            ml_running.set()
            threading.Thread(
                target=_run_ml,
                args=(latest_raw.copy(), args.worker, args.zone),
                daemon=True
            ).start()

        # Build display — use latest annotated frame or raw
        with display_lock:
            show = (display_frame.copy()
                    if display_frame is not None
                    else latest_raw.copy())

        # FPS counter
        fps_times.append(now)
        fps_times[:] = [t for t in fps_times if now - t < 1.0]
        avg_fps = len(fps_times)

        h, w = show.shape[:2]
        zone  = last_result.get("zone_summary", {})
        risk  = zone.get("zone_risk_level", "normal")
        rc    = RISK_COLORS.get(risk, (0, 200, 80))

        pending = _offline_queue.pending_count()
        offline_tag = f"  OFFLINE-QUEUE:{pending}" if pending else ""

        cv2.rectangle(show, (0, h-28), (w, h), (0, 0, 0), -1)
        cv2.putText(show,
                    f"FPS:{avg_fps:3d}  Workers:{zone.get('worker_count',0):2d}"
                    f"  Falls:{zone.get('fall_events',0)}"
                    f"  PPE Issues:{zone.get('ppe_violations',0)}"
                    f"  Risk:{risk.upper()}"
                    f"  Voice:{'OFF' if voice.muted else 'ON'}"
                    f"{offline_tag}",
                    (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 100, 255) if pending else rc, 1)

        if show_window:
            cv2.imshow("FieldPilot AI  [Q=quit | S=snapshot | M=mute]", show)

        key = cv2.waitKey(1) & 0xFF if show_window else (time.sleep(0.001) or 0xFF)
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            snap = os.path.join(ROOT, "data", f"snap_{int(time.time())}.jpg")
            cv2.imwrite(snap, show)
            print(f"Snapshot: {snap}")
        elif key == ord("m"):
            voice.muted = not voice.muted
            print(f"Voice: {'MUTED' if voice.muted else 'ON'}")

    grabber.stop()
    cap.release()
    cv2.destroyAllWindows()
    print("Pipeline stopped.")


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        description="FieldPilot AI — Live Camera Pipeline v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  python scripts/live_camera_pipeline.py                       # laptop + voice
  python scripts/live_camera_pipeline.py --source phone \\
         --phone-ip 192.168.1.42                               # phone camera
  python scripts/live_camera_pipeline.py --source video        # video file
  python scripts/live_camera_pipeline.py --no-stream           # standalone
  python scripts/live_camera_pipeline.py --how-to-find-ip      # phone IP guide
""",
    )
    p.add_argument("--source",         choices=["laptop","phone","video"], default="laptop")
    p.add_argument("--cam-index",      type=int, default=0)
    p.add_argument("--phone-ip",       type=str, default="YOUR_PHONE_IP")
    p.add_argument("--phone-port",     type=int, default=PHONE_PORT)
    p.add_argument("--zone",           type=str, default=DEFAULT_ZONE)
    p.add_argument("--worker",         type=str, default=DEFAULT_WORKER)
    p.add_argument("--api",            type=str, default=DEFAULT_API)
    p.add_argument("--no-stream",      action="store_true")
    p.add_argument("--headless",       action="store_true")
    p.add_argument("--mute",           action="store_true")
    p.add_argument("--how-to-find-ip", action="store_true")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    main(args)
