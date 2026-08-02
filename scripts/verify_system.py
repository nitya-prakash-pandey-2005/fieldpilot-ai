#!/usr/bin/env python
"""
FieldPilot AI — full end-to-end system verification.

One command that exercises every agent against a running backend and prints a
pass/fail table. Run it before a demo, after changing anything, and after
dropping new model weights in.

    # terminal 1
    cd api
    python -m uvicorn main:app --host 0.0.0.0 --port 8000

    # terminal 2 (from the repo root)
    python scripts/verify_system.py

    # against a different host/port
    python scripts/verify_system.py --base-url http://192.168.1.42:8000

Exit code is 0 only if every REQUIRED check passes. Checks that depend on
optional infrastructure (Neo4j, Qdrant, API keys) are reported as DEGRADED, not
FAILED — the system is designed to keep working without them, and this script
holds it to that.

  PASS      working
  DEGRADED  infrastructure missing, handled correctly, demo still works
  FAIL      broken — fix before demoing
  SKIP      not applicable
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Verification writes real rows (a FAIL verdict creates a real FieldIssue), so
# it runs against a dedicated zone rather than the demo zones. Without this, a
# pre-demo check inflates Zone A12's risk score and litters the dashboard with
# CRITICAL issues that a judge will see — observed live: A12's RFI risk climbed
# 0.874 -> 0.965 across two verification runs.
VERIFY_ZONE = "ZZ-VERIFY"
VERIFY_WORKER = "W-VERIFY"

PASS, DEGRADED, FAIL, SKIP = "PASS", "DEGRADED", "FAIL", "SKIP"
COLOR = {PASS: "\033[92m", DEGRADED: "\033[93m", FAIL: "\033[91m", SKIP: "\033[90m"}
RESET = "\033[0m"

results: list[tuple[str, str, str, str]] = []   # (group, name, status, detail)


def record(group: str, name: str, status: str, detail: str = "") -> None:
    results.append((group, name, status, detail))
    tick = {PASS: "PASS", DEGRADED: "DEGR", FAIL: "FAIL", SKIP: "SKIP"}[status]
    print(f"  {COLOR[status]}[{tick}]{RESET} {name}" + (f"  — {detail}" if detail else ""))


class Api:
    def __init__(self, base_url: str, token: str | None = None):
        self.base = base_url.rstrip("/")
        self.token = token

    def __call__(self, method: str, path: str, body=None, timeout=120, raw=False):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
                if raw:
                    return r.status, payload, time.time() - t0
                return r.status, json.loads(payload.decode() or "{}"), time.time() - t0
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:400]
            try:
                return e.code, json.loads(body_text), time.time() - t0
            except Exception:
                return e.code, {"_raw": body_text}, time.time() - t0
        except Exception as e:
            return 0, {"_err": str(e)[:200]}, time.time() - t0


# ---------------------------------------------------------------------------

def port_open(host: str, port: int, timeout=1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def check_infrastructure() -> None:
    print("\n\033[1mINFRASTRUCTURE\033[0m")
    services = [("Postgres", 5432), ("Qdrant", 6333), ("Redis", 6379), ("Neo4j", 7687)]
    up = 0
    for name, port in services:
        if port_open("127.0.0.1", port):
            record("infra", f"{name} (:{port})", PASS)
            up += 1
        else:
            record("infra", f"{name} (:{port})", DEGRADED,
                   "not running — the API falls back, but this feature degrades")
    if up == 0:
        print("     \033[93mNo containers running. Start them with: docker compose up -d\033[0m")
        print("     \033[93mThe demo still works, but on SQLite with no graph/vector search.\033[0m")


def check_backend(api: Api) -> bool:
    print("\n\033[1mBACKEND\033[0m")
    status, body, dt = api("GET", "/api/v1/health", timeout=10)
    if status != 200:
        record("backend", "API reachable", FAIL,
               f"{api.base} — {body.get('_err') or status}. Is uvicorn running? "
               f"(cd api; python -m uvicorn main:app --host 0.0.0.0 --port 8000)")
        return False
    record("backend", "API reachable", PASS, f"{api.base} ({dt*1000:.0f}ms)")

    status, body, _ = api("GET", "/api/v1/health/agents")
    if status == 200:
        agents = body.get("agents", {})
        operational = sum(1 for v in agents.values() if v == "operational")
        record("backend", "Agent health", PASS if operational else DEGRADED,
               f"{operational}/{len(agents)} operational")
    else:
        record("backend", "Agent health", FAIL, f"HTTP {status}")
    return True


def check_auth(api: Api) -> str | None:
    print("\n\033[1mAUTH\033[0m")
    status, body, _ = api("POST", "/api/v1/auth/login",
                          {"email": "engineer@fieldpilot.demo", "password": "fieldpilot123"})
    token = body.get("access_token") if status == 200 else None
    if token:
        record("auth", "Login (engineer@fieldpilot.demo)", PASS)
    else:
        record("auth", "Login", FAIL, f"HTTP {status} {str(body)[:120]}")
        return None

    status, _, _ = api("GET", "/api/v1/graph/query")   # no token on this instance
    bad = Api(api.base)
    status, _, _ = bad("POST", "/api/v1/graph/query", {"query": "MATCH (n) RETURN n LIMIT 1"})
    if status in (401, 403):
        record("auth", "Cypher endpoint rejects unauthenticated", PASS, f"HTTP {status}")
    else:
        record("auth", "Cypher endpoint rejects unauthenticated", FAIL,
               f"expected 401/403, got {status} — raw Cypher is exposed")
    return token


def check_measurement(api: Api) -> None:
    """Agent 2 — the pitch deck's headline. Synthesises a grid with known
    geometry, so this is a real accuracy check, not just a liveness ping."""
    print("\n\033[1mAGENT 2 — MEASUREMENT (deck headline)\033[0m")
    try:
        import cv2
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        os.environ.setdefault("DEPTH_ENABLED", "0")
        from test_measurement import build_grid_scene
    except Exception as e:
        record("measurement", "Synthetic scene", SKIP, f"cannot build test scene: {e}")
        return

    status, body, _ = api("GET", "/api/v1/measurement/status")
    if status == 200:
        record("measurement", "Engine status", PASS,
               f"calibration={body.get('calibration_backend')}, "
               f"rebar_model={'yes' if body.get('rebar_model') else 'not trained yet'}")

    for truth, label, expect in ((150.0, "compliant grid", "PASS"),
                                 (190.0, "deviation grid", "FAIL")):
        img = build_grid_scene(spacing_mm=truth)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        status, body, dt = api("POST", "/api/v1/measurement/validate", {
            "frame": base64.b64encode(buf).decode(), "zone_id": VERIFY_ZONE,
            "worker_id": VERIFY_WORKER, "parameter": "spacing", "expected_value": 150,
            "tolerance_min": 140, "tolerance_max": 160})

        if status != 200:
            record("measurement", f"{label}", FAIL, f"HTTP {status} {str(body)[:120]}")
            continue

        verdict = body.get("verdict")
        meas = (body.get("measurement", {}).get("measurements") or [{}])[0]
        value = meas.get("value")
        err = abs(value - truth) if isinstance(value, (int, float)) else None

        if verdict != expect:
            record("measurement", label, FAIL,
                   f"expected {expect}, got {verdict} (measured {value})")
        elif err is not None and err > 6.0:
            record("measurement", label, FAIL,
                   f"{verdict} but measured {value}mm vs {truth}mm truth (err {err:.1f}mm)")
        else:
            spoken = ((body.get("validation") or {}).get("explanation") or {}).get("glasses_audio", "")
            record("measurement", label, PASS,
                   f"{verdict} · {value}mm (err {err:.1f}mm) · {dt*1000:.0f}ms")
            if spoken:
                print(f"          spoken: \"{spoken.strip()}\"")

    # The refusal case matters as much as the success case.
    img = build_grid_scene(spacing_mm=150.0, with_marker=False)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    status, body, _ = api("POST", "/api/v1/measurement/validate", {
        "frame": base64.b64encode(buf).decode(), "zone_id": VERIFY_ZONE,
        "worker_id": VERIFY_WORKER, "parameter": "spacing", "expected_value": 150,
        "tolerance_min": 140, "tolerance_max": 160})
    if status == 200 and body.get("verdict") == "UNCERTAIN":
        record("measurement", "Refuses without a scale reference", PASS,
               "returns UNCERTAIN instead of guessing")
    else:
        record("measurement", "Refuses without a scale reference", FAIL,
               f"got {body.get('verdict')} — it should NOT produce a number here")


def check_predictive_rfi(api: Api) -> None:
    print("\n\033[1mAGENT 6 — PREDICTIVE RFI\033[0m")
    scores = {}
    for zone, activity in (("A12", "Rebar installation"), ("B3", "MEP rough-in"),
                           ("C7", "Concrete curing")):
        status, body, dt = api("POST", "/api/v1/rfi/predict", {
            "project_id": "default-project", "zone_id": zone,
            "current_activity": {"work_type": activity, "drawing_refs": ["S-101-R5"],
                                 "scheduled_completion": "2026-09-01"}}, timeout=180)
        pred = body.get("prediction") or {}
        risk = pred.get("rfi_risk_score")
        mode = (pred.get("risk_model") or {}).get("scoring_mode")
        scores[zone] = risk
        if status == 200 and risk is not None:
            record("rfi", f"Zone {zone} ({activity})", PASS,
                   f"risk={risk} asset={pred.get('asset_type')} mode={mode} ({dt:.1f}s)")
            if pred.get("narrative_unavailable"):
                print(f"          narrative unavailable: {pred['narrative_unavailable'][:80]}")
        else:
            record("rfi", f"Zone {zone}", FAIL, f"HTTP {status} {str(body)[:120]}")

    distinct = len({str(v) for v in scores.values() if v is not None})
    if distinct > 1:
        record("rfi", "Scores vary by zone (not a constant mock)", PASS,
               ", ".join(f"{k}={v}" for k, v in scores.items()))
    elif distinct == 1:
        record("rfi", "Scores vary by zone", FAIL,
               "every zone returned the same score — check the risk model")


def check_vision(api: Api) -> None:
    print("\n\033[1mAGENT 1 — VISION\033[0m")
    try:
        import cv2
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        from test_measurement import build_grid_scene
        img = build_grid_scene(spacing_mm=150.0)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    except Exception as e:
        record("vision", "Scene analysis", SKIP, str(e))
        return

    status, body, dt = api("POST", "/api/v1/vision/understand", {
        "image": base64.b64encode(buf).decode(), "zone_id": VERIFY_ZONE,
        "language": "en", "project_id": "default-project",
        "worker_id": VERIFY_WORKER}, timeout=180)

    if status != 200:
        record("vision", "Scene analysis (VLM + YOLO)", FAIL, f"HTTP {status} {str(body)[:120]}")
        return
    scene = body.get("scene") or {}
    desc = (scene.get("scene_description") or "")[:70]
    if scene.get("confidence", 0) == 0 and "Error" in desc:
        record("vision", "Scene analysis (VLM + YOLO)", DEGRADED,
               f"VLM unavailable: {desc}")
    else:
        record("vision", "Scene analysis (VLM + YOLO)", PASS, f"{desc} ({dt:.1f}s)")


def check_memory(api: Api) -> None:
    print("\n\033[1mAGENT 7 — PROJECT MEMORY (RAG)\033[0m")
    status, body, _ = api("GET", "/api/v1/memory/stats")
    indexed = (body.get("data") or {}).get("indexed_passages", 0) if status == 200 else 0
    record("memory", "Index", PASS if indexed else DEGRADED,
           f"{indexed} passages indexed"
           + ("" if indexed else " — run scripts/ingest_spec.py to load the OSHA PDFs"))

    status, body, dt = api("POST", "/api/v1/memory/query", {
        "query": "What does OSHA require for fall protection?",
        "project_id": "default-project", "zone_id": VERIFY_ZONE, "worker_id": VERIFY_WORKER},
        timeout=120)
    if status != 200:
        record("memory", "Cited Q&A", FAIL, f"HTTP {status}")
    elif body.get("status") == "degraded":
        record("memory", "Cited Q&A", DEGRADED,
               f"{body.get('error_class')} — correctly returns no fabricated answer")
    else:
        answer = str(body.get("answer") or "")[:70]
        n_ev = len(body.get("evidence") or [])
        record("memory", "Cited Q&A", PASS if n_ev else DEGRADED,
               f"{n_ev} citations · {answer} ({dt:.1f}s)")


def check_voice(api: Api) -> None:
    print("\n\033[1mAGENT 11 — VOICE\033[0m")
    status, body, _ = api("GET", "/api/v1/voice/status")
    if status != 200:
        record("voice", "Voice pipeline", FAIL, f"HTTP {status}")
        return
    for leg in ("stt", "llm", "tts"):
        cfg = body.get(leg) or {}
        record("voice", f"{leg.upper()} configured",
               PASS if cfg.get("configured") else DEGRADED,
               cfg.get("model") or cfg.get("provider") or "")


def check_graph_and_degradation(api: Api) -> None:
    print("\n\033[1mAGENT 4 — KNOWLEDGE GRAPH + DEGRADATION\033[0m")
    status, body, _ = api("GET", "/api/v1/graph/project/default-project/zones")
    if status != 200:
        record("graph", "Zone list", FAIL, f"HTTP {status} — should degrade, not error")
        return
    source = body.get("source")
    n = len(body.get("data") or [])
    if body.get("status") == "degraded":
        record("graph", "Zone list", DEGRADED,
               f"Neo4j down — served {n} REAL zones from {source} (not fabricated)")
    else:
        record("graph", "Zone list", PASS, f"{n} zones from {source}")


def check_interactions(api: Api) -> None:
    print("\n\033[1mAUDIT TRAIL\033[0m")
    status, body, _ = api("GET", "/api/v1/interactions?limit=20")
    if status != 200:
        record("audit", "Interaction feed", FAIL, f"HTTP {status}")
        return
    n = body.get("count", 0)
    if body.get("status") == "degraded":
        record("audit", "Interaction feed", DEGRADED, body.get("error", "")[:80])
    else:
        record("audit", "Interaction feed", PASS,
               f"{n} recorded (the checks above should have added some)")

    status, stats, _ = api("GET", "/api/v1/interactions/stats")
    if status == 200:
        record("audit", "Stats aggregate", PASS,
               f"by_kind={stats.get('by_kind')} by_verdict={stats.get('by_verdict')}")


def check_mobile_reachability(api: Api) -> None:
    print("\n\033[1mMOBILE REACHABILITY\033[0m")
    lan_ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and ip not in lan_ips:
                lan_ips.append(ip)
    except Exception:
        pass

    if "0.0.0.0" not in api.base and ("127.0.0.1" in api.base or "localhost" in api.base):
        # Are we actually bound to all interfaces? Try the LAN IP.
        reachable = [ip for ip in lan_ips if port_open(ip, 8000, timeout=1.0)]
        if reachable:
            record("mobile", "API reachable on LAN", PASS,
                   f"phone should use http://{reachable[0]}:8000")
        else:
            record("mobile", "API reachable on LAN", DEGRADED,
                   "bound to loopback only — a phone cannot connect. Restart with "
                   "--host 0.0.0.0 (see below)")
    if lan_ips:
        print(f"     LAN addresses: {', '.join(lan_ips)}")


async def cleanup_verification_data() -> str:
    """Delete the rows this script created.

    Verification exercises real write paths — a FAIL verdict genuinely creates a
    FieldIssue — so without this a pre-demo check leaves fake CRITICAL issues on
    the dashboard. Everything written is tagged with VERIFY_ZONE / VERIFY_WORKER
    and nothing else uses those, so this can't touch real data.
    """
    sys.path.insert(0, str(REPO / "api"))
    try:
        from db import async_session
        from models.compliance import ComplianceEvent
        from models.interaction import Interaction
        from models.issues import FieldIssue
        from sqlalchemy import delete, or_

        removed = {}
        async with async_session() as s:
            for model, cond, label in (
                (FieldIssue, FieldIssue.zone_code == VERIFY_ZONE, "field_issues"),
                (ComplianceEvent, ComplianceEvent.zone_code == VERIFY_ZONE, "compliance_events"),
                (Interaction, or_(Interaction.zone_code == VERIFY_ZONE,
                                  Interaction.worker_id == VERIFY_WORKER), "interactions"),
            ):
                try:
                    result = await s.execute(delete(model).where(cond))
                    removed[label] = result.rowcount or 0
                except Exception as e:
                    removed[label] = f"skipped ({type(e).__name__})"
            await s.commit()
        return ", ".join(f"{k}={v}" for k, v in removed.items())
    except Exception as e:
        return f"cleanup unavailable: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--skip-slow", action="store_true",
                    help="skip the LLM-backed checks (RFI, vision, memory)")
    ap.add_argument("--keep-data", action="store_true",
                    help="don't delete the rows this run created (default: clean up, "
                         "so a pre-demo check leaves no fake issues on the dashboard)")
    args = ap.parse_args()

    print("=" * 74)
    print(f"  FieldPilot AI — system verification against {args.base_url}")
    print("=" * 74)

    check_infrastructure()

    api = Api(args.base_url)
    if not check_backend(api):
        print("\n\033[91mBackend unreachable — nothing else can be checked.\033[0m")
        print("\n  Start it with:")
        print("    cd api")
        print("    python -m uvicorn main:app --host 0.0.0.0 --port 8000")
        print("\n  (main.py lives in api/, so `cd api` first — running from the repo")
        print("   root gives 'Could not import module \"main\"'.)")
        return 1

    api.token = check_auth(api)
    check_measurement(api)
    check_graph_and_degradation(api)
    check_voice(api)
    if not args.skip_slow:
        check_vision(api)
        check_memory(api)
        check_predictive_rfi(api)
    check_interactions(api)
    check_mobile_reachability(api)

    # ---- summary ----
    counts = {PASS: 0, DEGRADED: 0, FAIL: 0, SKIP: 0}
    for _, _, status, _ in results:
        counts[status] += 1

    print("\n" + "=" * 74)
    print(f"  {COLOR[PASS]}{counts[PASS]} passed{RESET}   "
          f"{COLOR[DEGRADED]}{counts[DEGRADED]} degraded{RESET}   "
          f"{COLOR[FAIL]}{counts[FAIL]} failed{RESET}   "
          f"{COLOR[SKIP]}{counts[SKIP]} skipped{RESET}")
    print("=" * 74)

    if counts[FAIL]:
        print("\n\033[91mFAILURES — fix these before demoing:\033[0m")
        for group, name, status, detail in results:
            if status == FAIL:
                print(f"  · [{group}] {name}: {detail}")
    if counts[DEGRADED]:
        print("\n\033[93mDEGRADED — the demo works, but these features are limited:\033[0m")
        for group, name, status, detail in results:
            if status == DEGRADED:
                print(f"  · [{group}] {name}: {detail}")

    if args.keep_data:
        print(f"\n  Verification rows kept (zone {VERIFY_ZONE}, worker {VERIFY_WORKER}).")
    else:
        import asyncio
        detail = asyncio.run(cleanup_verification_data())
        print(f"\n  Cleaned up verification data: {detail}")

    if not counts[FAIL]:
        print("\n\033[92mNo failures. The demo path is working.\033[0m")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
