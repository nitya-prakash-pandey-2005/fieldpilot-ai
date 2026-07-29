"""
Load Test — FieldPilot AI
----------------------------
Simulates N concurrent workers each continuously POSTing live frame events
and compliance validations against the real running backend, to close the
testing matrix's "Load — backend holds up under simulated load of at least
3 concurrent workers' event streams without dropped events" row with a real
measured number instead of an unverified claim.

Usage:
  python scripts/load_test.py --workers 5 --duration 30
"""

import argparse
import asyncio
import random
import statistics
import time
import uuid

import httpx


async def simulate_live_frame_worker(client: httpx.AsyncClient, base_url: str, worker_id: str, zone_id: str,
                                      duration_s: float, results: list):
    end = time.monotonic() + duration_s
    tiny_jpeg_b64 = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
        "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQ"
        "EBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIA"
        "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEB"
        "AQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
    )
    while time.monotonic() < end:
        payload = {
            "worker_id": worker_id,
            "zone_id": zone_id,
            "frame": tiny_jpeg_b64,
            "detections": {
                "zone_summary": {"zone_risk_level": "normal", "zone_risk_score": 10, "worker_count": 1},
                "compliance": [{"ppe_score": 1.0}],
                "fall_events": [],
            },
        }
        start = time.monotonic()
        try:
            resp = await client.post(f"{base_url}/api/v1/live/frame", json=payload, timeout=10.0)
            elapsed = time.monotonic() - start
            results.append(("live/frame", resp.status_code, elapsed))
        except Exception as e:
            elapsed = time.monotonic() - start
            results.append(("live/frame", f"ERROR:{e}", elapsed))
        await asyncio.sleep(0.5)  # ~2 frames/sec per worker, realistic for a live pipeline


async def simulate_compliance_worker(client: httpx.AsyncClient, base_url: str, worker_id: str, zone_id: str,
                                      duration_s: float, results: list):
    end = time.monotonic() + duration_s
    while time.monotonic() < end:
        measured = random.uniform(140, 210)
        payload = {
            "observation_id": str(uuid.uuid4()),
            "asset_id": f"rebar_{worker_id}",
            "zone_id": zone_id,
            "measurement": {"parameter": "spacing", "measured_value": measured, "unit": "mm", "confidence": 0.9},
            "specification": {
                "spec_id": "S-101-R5",
                "expected_value": 150,
                "tolerance_min": 140,
                "tolerance_max": 160,
                "unit": "mm",
                "standard_ref": "ACI 318-19 Section 7.7.1",
            },
        }
        start = time.monotonic()
        try:
            resp = await client.post(f"{base_url}/api/v1/compliance/validate", json=payload, timeout=10.0)
            elapsed = time.monotonic() - start
            results.append(("compliance/validate", resp.status_code, elapsed))
        except Exception as e:
            elapsed = time.monotonic() - start
            results.append(("compliance/validate", f"ERROR:{e}", elapsed))
        await asyncio.sleep(1.0)


async def run_load_test(base_url: str, n_workers: int, duration_s: float):
    results: list[tuple[str, object, float]] = []
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(n_workers):
            worker_id = f"load-test-worker-{i+1}"
            zone_id = ["A12", "B3", "C7"][i % 3]
            tasks.append(simulate_live_frame_worker(client, base_url, worker_id, zone_id, duration_s, results))
            tasks.append(simulate_compliance_worker(client, base_url, worker_id, zone_id, duration_s, results))
        await asyncio.gather(*tasks)
    return results


def summarize(results: list[tuple[str, object, float]]):
    by_endpoint: dict[str, list[tuple[object, float]]] = {}
    for endpoint, status, elapsed in results:
        by_endpoint.setdefault(endpoint, []).append((status, elapsed))

    print(f"\n{'='*60}\nLOAD TEST RESULTS\n{'='*60}")
    total_requests = len(results)
    total_errors = sum(1 for _, status, _ in results if not (isinstance(status, int) and 200 <= status < 300))
    print(f"Total requests: {total_requests}  |  Failed: {total_errors}  |  Success rate: {100*(total_requests-total_errors)/max(total_requests,1):.1f}%\n")

    for endpoint, rows in by_endpoint.items():
        latencies = [e for _, e in rows]
        errors = [s for s, _ in rows if not (isinstance(s, int) and 200 <= s < 300)]
        latencies_sorted = sorted(latencies)
        p50 = statistics.median(latencies_sorted) if latencies_sorted else 0
        p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0
        print(f"[{endpoint}]")
        print(f"  requests: {len(rows)}  errors: {len(errors)}")
        print(f"  latency  median: {p50*1000:.0f}ms   p95: {p95*1000:.0f}ms   max: {max(latencies)*1000:.0f}ms" if latencies else "  no data")
        if errors:
            print(f"  sample errors: {errors[:3]}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workers", type=int, default=5, help="Number of simulated concurrent workers (>=3 required by testing matrix)")
    parser.add_argument("--duration", type=float, default=20.0, help="Test duration in seconds")
    args = parser.parse_args()

    print(f"Starting load test: {args.workers} concurrent workers for {args.duration}s against {args.base_url}...")
    results = asyncio.run(run_load_test(args.base_url, args.workers, args.duration))
    summarize(results)
