#!/usr/bin/env python
"""
BLE beacon simulator — walks a virtual worker around the site.

Real beacons are £15 each and need physically mounting and surveying. This
reproduces exactly what the phone's radio would report — beacon identifier plus
RSSI, nothing more — so the entire localization path (registry lookup, temporal
smoothing, multilateration, zone assignment, position trail, the dashboard map)
is exercised end to end against the real API before any hardware exists.

It is a simulator of the RADIO, not of the answer. It computes true distances
from a real floor plan, converts them through the same log-distance path loss
model the solver inverts, and adds Gaussian fading plus occasional body-blocking
dropouts. The server still has to do all the work; the simulator never tells it
a zone.

    # register the beacon layout, then walk a worker through it
    python scripts/ble_simulator.py --setup
    python scripts/ble_simulator.py --worker W-022 --duration 120

    # several workers at once, to see the live map populate
    python scripts/ble_simulator.py --workers W-022,W-015,W-088 --duration 300

Watch it land:
    curl http://127.0.0.1:8000/api/v1/localization/live
    curl http://127.0.0.1:8000/api/v1/localization/worker/W-022?trail=20
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agents.localization.rssi import DEFAULT_TX_POWER_DBM, distance_to_rssi

# ---------------------------------------------------------------------------
# A plausible site layout, matching the seeded zones A12 / B3 / C7.
# Coordinates are site-plan metres. Four beacons per bay so every zone can be
# fully trilaterated (3 is the minimum; 4 gives redundancy when one is blocked).
# ---------------------------------------------------------------------------
BEACON_LAYOUT = [
    # Zone A12 — Foundation Level 1 North, 20 x 15 m bay at origin
    ("BCN-A12-1", "A12", 0.0, 0.0, 0, "Column A1 north face"),
    ("BCN-A12-2", "A12", 20.0, 0.0, 0, "Column A4 north face"),
    ("BCN-A12-3", "A12", 20.0, 15.0, 0, "Column D4 south face"),
    ("BCN-A12-4", "A12", 0.0, 15.0, 0, "Column D1 south face"),
    # Zone B3 — Podium Level 3 East, 18 x 12 m bay offset east
    ("BCN-B3-1", "B3", 35.0, 0.0, 3, "Column E1 west face"),
    ("BCN-B3-2", "B3", 53.0, 0.0, 3, "Column H1 east face"),
    ("BCN-B3-3", "B3", 53.0, 12.0, 3, "Column H3 east face"),
    ("BCN-B3-4", "B3", 35.0, 12.0, 3, "Column E3 west face"),
    # Zone C7 — Tower Floor 12 Core, 14 x 14 m core offset north
    ("BCN-C7-1", "C7", 0.0, 30.0, 12, "Core wall NW"),
    ("BCN-C7-2", "C7", 14.0, 30.0, 12, "Core wall NE"),
    ("BCN-C7-3", "C7", 14.0, 44.0, 12, "Core wall SE"),
    ("BCN-C7-4", "C7", 0.0, 44.0, 12, "Core wall SW"),
]

# Patrol route per zone: the centre of each bay, so a worker "walks" between them.
ZONE_CENTRES = {
    "A12": (10.0, 7.5, 0),
    "B3": (44.0, 6.0, 3),
    "C7": (7.0, 37.0, 12),
}

# Radio realism knobs.
FADING_STD_DB = 4.0        # normal BLE fast-fading, stationary phone
BODY_BLOCK_DB = 12.0       # worker's torso between phone and beacon
BODY_BLOCK_CHANCE = 0.12
DROPOUT_CHANCE = 0.08      # advertisement missed entirely in a scan window
# Beyond this the phone simply doesn't hear the beacon.
MAX_RANGE_M = 30.0


def post(base: str, path: str, body: dict, timeout: float = 15.0) -> tuple[int, dict]:
    req = urllib.request.Request(base.rstrip("/") + path,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()[:300]
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw}
    except Exception as e:
        return 0, {"_err": str(e)[:200]}


def setup_beacons(base: str, token: str | None) -> int:
    """Register the layout. Requires an engineer+ token — beacon coordinates
    decide which spec every observation is judged against, so the API does not
    let a worker write them."""
    payload = [{
        "beacon_id": bid, "zone_code": zone, "x": x, "y": y, "floor": floor,
        "label": label, "tx_power": DEFAULT_TX_POWER_DBM,
        "project_id": "default-project",
    } for bid, zone, x, y, floor, label in BEACON_LAYOUT]

    req = urllib.request.Request(base.rstrip("/") + "/api/v1/localization/beacons",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
        print(f"  registered {body.get('created', 0)} new, updated {body.get('updated', 0)}")
        return 0
    except urllib.error.HTTPError as e:
        print(f"  FAILED HTTP {e.code}: {e.read().decode()[:200]}")
        if e.code in (401, 403):
            print("  (needs an engineer/pm/admin token — the simulator logs in "
                  "automatically, so check the demo credentials)")
        return 1
    except Exception as e:
        print(f"  FAILED: {e}")
        return 1


def login(base: str) -> str | None:
    status, body = post(base, "/api/v1/auth/login",
                        {"email": "engineer@fieldpilot.demo", "password": "fieldpilot123"})
    return body.get("access_token") if status == 200 else None


def scan_at(x: float, y: float, floor: int, rng: random.Random) -> list[dict]:
    """What the phone's radio hears at this point. Identifier + RSSI only."""
    readings = []
    for bid, zone, bx, by, bfloor, _label in BEACON_LAYOUT:
        d = math.hypot(x - bx, y - by)
        # Concrete slabs attenuate heavily between floors; treat other floors as
        # effectively invisible rather than modelling slab loss precisely.
        if bfloor != floor:
            continue
        if d > MAX_RANGE_M:
            continue
        if rng.random() < DROPOUT_CHANCE:
            continue
        rssi = distance_to_rssi(d)
        rssi += rng.gauss(0.0, FADING_STD_DB)
        if rng.random() < BODY_BLOCK_CHANCE:
            rssi -= BODY_BLOCK_DB
        readings.append({"beacon_id": bid, "rssi": round(max(rssi, -110.0), 1)})
    return readings


def walk(duration_s: int, rng: random.Random, start_zone: str):
    """Yield (x, y, floor, true_zone) once per second along a patrol route.

    Workers do not teleport: the path interpolates between zone centres, so the
    solver sees a continuous track and the smoother is exercised the way it would
    be in reality (including the transition, where zone assignment is hardest).
    """
    zones = list(ZONE_CENTRES)
    idx = zones.index(start_zone) if start_zone in zones else 0
    t = 0
    # Dwell in a zone, then transit to the next.
    while t < duration_s:
        zone = zones[idx]
        cx, cy, floor = ZONE_CENTRES[zone]
        dwell = rng.randint(20, 40)
        for _ in range(min(dwell, duration_s - t)):
            # Wander within a few metres of the bay centre.
            yield (cx + rng.uniform(-5, 5), cy + rng.uniform(-4, 4), floor, zone)
            t += 1
        if t >= duration_s:
            break
        nxt = zones[(idx + 1) % len(zones)]
        nx, ny, nfloor = ZONE_CENTRES[nxt]
        steps = rng.randint(8, 14)
        for k in range(min(steps, duration_s - t)):
            f = (k + 1) / steps
            # Floor changes discretely partway through (taking a hoist/stair).
            yield (cx + (nx - cx) * f, cy + (ny - cy) * f,
                   floor if f < 0.5 else nfloor, zone if f < 0.5 else nxt)
            t += 1
        idx = (idx + 1) % len(zones)


def run_worker(base: str, worker_id: str, duration_s: int, rate_hz: float,
               seed: int, quiet: bool) -> dict:
    rng = random.Random(seed)
    start = list(ZONE_CENTRES)[seed % len(ZONE_CENTRES)]
    correct = total = 0
    errors: list[float] = []
    interval = 1.0 / max(rate_hz, 0.1)

    for x, y, floor, true_zone in walk(duration_s, rng, start):
        readings = scan_at(x, y, floor, rng)
        if not readings:
            time.sleep(interval)
            continue

        status, body = post(base, "/api/v1/localization/scan", {
            "worker_id": worker_id, "beacons": readings,
            "project_id": "default-project",
        })
        if status != 200:
            print(f"  [{worker_id}] scan rejected: HTTP {status} {str(body)[:120]}")
            time.sleep(interval)
            continue

        total += 1
        resolved = body.get("zone_code")
        pos = body.get("position") or {}
        if resolved == true_zone:
            correct += 1
        if pos.get("x") is not None:
            errors.append(math.hypot(pos["x"] - x, pos["y"] - y))

        if not quiet:
            mark = "ok " if resolved == true_zone else "MISS"
            err = f"{math.hypot(pos['x'] - x, pos['y'] - y):5.2f}m" if pos.get("x") is not None else "  n/a"
            print(f"  [{worker_id}] true {true_zone:<4} -> {str(resolved):<4} {mark} "
                  f"err {err}  {pos.get('method', '?'):<16} "
                  f"conf {pos.get('confidence', 0):.2f}  beacons {pos.get('beacons_used', 0)}")

        time.sleep(interval)

    return {
        "worker_id": worker_id,
        "scans": total,
        "zone_accuracy": (correct / total) if total else 0.0,
        "mean_position_error_m": (sum(errors) / len(errors)) if errors else None,
        "p90_position_error_m": (sorted(errors)[int(len(errors) * 0.9)] if len(errors) >= 10 else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--setup", action="store_true", help="register the beacon layout and exit")
    ap.add_argument("--worker", default="W-022")
    ap.add_argument("--workers", default=None, help="comma-separated, run concurrently")
    ap.add_argument("--duration", type=int, default=60, help="seconds of simulated walking")
    ap.add_argument("--rate", type=float, default=1.0, help="scans per second")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    token = login(args.base_url)
    if token is None:
        print("⚠ could not log in — is the backend running at "
              f"{args.base_url}? (cd api; python -m uvicorn main:app --host 0.0.0.0 --port 8000)")
        return 1

    print(f"▶ registering {len(BEACON_LAYOUT)} beacons across "
          f"{len(ZONE_CENTRES)} zones")
    if setup_beacons(args.base_url, token) != 0:
        return 1
    if args.setup:
        print("\nBeacon layout registered. Check it:")
        print(f"  curl {args.base_url}/api/v1/localization/status")
        return 0

    workers = [w.strip() for w in (args.workers or args.worker).split(",") if w.strip()]
    print(f"\n▶ simulating {len(workers)} worker(s) for {args.duration}s at {args.rate} Hz")
    print("  (the simulator sends only beacon_id + RSSI — the server resolves the zone)\n")

    if len(workers) == 1:
        summaries = [run_worker(args.base_url, workers[0], args.duration,
                                args.rate, 0, args.quiet)]
    else:
        import threading
        results: list[dict] = []
        lock = threading.Lock()

        def target(wid: str, seed: int):
            r = run_worker(args.base_url, wid, args.duration, args.rate, seed, args.quiet)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=target, args=(w, i), daemon=True)
                   for i, w in enumerate(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        summaries = results

    print("\n" + "=" * 68)
    print(f"  {'worker':<10}{'scans':>7}{'zone acc':>10}{'mean err':>11}{'p90 err':>10}")
    for s in summaries:
        mean = f"{s['mean_position_error_m']:.2f}m" if s["mean_position_error_m"] is not None else "n/a"
        p90 = f"{s['p90_position_error_m']:.2f}m" if s["p90_position_error_m"] is not None else "n/a"
        print(f"  {s['worker_id']:<10}{s['scans']:>7}{s['zone_accuracy']:>9.1%}{mean:>11}{p90:>10}")
    print("=" * 68)
    print("\n  Zone accuracy is the number that matters — it decides which")
    print("  blueprint an observation is checked against. Position error only")
    print("  affects where the dot sits on the site map.")
    print(f"\n  See it: curl {args.base_url}/api/v1/localization/live")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
