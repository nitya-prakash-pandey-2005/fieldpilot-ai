# FieldPilot AI — Full Testing Guide

Every command needed to stand up the whole system and verify each piece actually works, in order. Run these from the repo root (`D:\Kaya IIT Hackathon\fieldpilot-ai`) unless noted otherwise. Commands are given for PowerShell/Windows (this project's dev environment) — Bash equivalents are trivial substitutions where noted.

---

## 0. Login credentials

The dashboard requires login. Five demo accounts are auto-seeded on first backend startup, all with password **`fieldpilot123`**:

| Role | Email | What they see |
|---|---|---|
| Worker | `worker@fieldpilot.demo` | Command Center, Glasses Feed, Project Memory |
| Site Engineer | `engineer@fieldpilot.demo` | Everything except Executive Summary |
| Project Manager | `pm@fieldpilot.demo` | Everything |
| Admin | `admin@fieldpilot.demo` | Everything, including raw Cypher graph console |
| Executive | `executive@fieldpilot.demo` | Everything except Drawings/Knowledge Graph tools |

If you ever need a fresh set of credentials, log in as any account, or `POST /api/v1/auth/register` (see §6).

---

## 1. Prerequisites

- Docker Desktop (running)
- Python 3.11+ with the packages in `api/requirements.txt`
- Node.js 20+ with the frontend's `npm install` already run once

```powershell
# One-time setup
pip install -r api/requirements.txt
cd frontend/engineer-dashboard
npm install
cd ../..
```

---

## 2. Start the infrastructure (Postgres, Qdrant, Redis, Neo4j)

```powershell
docker compose up -d
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Expect 4 healthy containers: `fieldpilot_db`, `fieldpilot_qdrant`, `fieldpilot_redis`, `fieldpilot_neo4j`.

**Test:** all four show `Up ... (healthy)` or `Up ...` — if any is missing, check `docker compose logs <service>`.

---

## 3. Initialize the database (optional — the API does this automatically on startup)

```powershell
python scripts/init_db.py
```

**Expected output:** `✅ Tables ready: assets, compliance_events, field_issues, notification_audit, observations, projects, resolved_incidents, users, zone_alerts, zones`

---

## 4. Start the backend

```powershell
cd api
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Wait for `Application startup complete.` — first run downloads a few ML models (YOLO, PPE hardhat model), which takes ~20-30s.

**Test:**
```powershell
curl http://127.0.0.1:8000/api/v1/health
# Expect: {"status":"ok",...}

curl http://127.0.0.1:8000/api/v1/health/agents
# Expect: real per-agent status (operational/degraded), not a fixed hardcoded set
```

---

## 5. Start the frontend

In a **new terminal**:
```powershell
cd frontend/engineer-dashboard
npm run dev
```

Open **http://localhost:3000** — you should land on the login page. Log in with any account from §0.

---

## 6. Auth — verify the login system itself

```powershell
# Login
curl -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{"email":"engineer@fieldpilot.demo","password":"fieldpilot123"}'
# Expect: {"access_token": "...", "user": {...}}

# Save the token, then test the protected endpoint
$TOKEN = "<paste access_token here>"
curl http://127.0.0.1:8000/api/v1/graph/query -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"query":"MATCH (n) RETURN count(n) as c"}'
# Expect: 200 with real Cypher result

# Without a token, the same call should be rejected:
curl -X POST http://127.0.0.1:8000/api/v1/graph/query -H "Content-Type: application/json" -d '{"query":"MATCH (n) RETURN count(n)"}'
# Expect: 401 Unauthorized

# A "worker" role should be forbidden from the graph console (role gate, not just login gate):
curl -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{"email":"worker@fieldpilot.demo","password":"fieldpilot123"}'
# use that worker token on /graph/query -> expect 403
```

---

## 7. ML pipeline — run the full validation suite

```powershell
python scripts/validate_baseline.py --mode all
```

**Expected:** all four categories PASS at 100% (`ppe`, `fall`, `onnx`, `attention`). Results are saved to `models/evaluation/baseline_<timestamp>.json`. Individual modes:
```powershell
python scripts/validate_baseline.py --mode ppe        # hardhat present/absent, real photo-based
python scripts/validate_baseline.py --mode fall        # staged fall vs normal posture
python scripts/validate_baseline.py --mode onnx        # quantized model vs full model, 5-frame parity
python scripts/validate_baseline.py --mode attention   # PASSIVE/ACKNOWLEDGED/ESCALATED state machine
```

---

## 8. Vision pipeline — real end-to-end scene analysis

With the backend running:
```powershell
python -c "
import base64, requests
with open('data/demo_images/construction_worker_hazard_1783890327070.png', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
resp = requests.post('http://127.0.0.1:8000/api/v1/vision/understand', json={'image': b64, 'zone_id': 'A12', 'language': 'en'})
print(resp.status_code)
print(resp.json())
"
```
**Expected:** `200`, with a real `detections.assets_detected` list (person detected, PPE breakdown, pose keypoints). The `scene` field's VLM analysis needs a valid `GROQ_API_KEY` (see §11) — without one it gracefully returns a low-confidence fallback instead of crashing.

**In the browser:** go to **Glasses Feed** → Webcam or Upload Image → a real photo now gets genuinely analyzed (not a canned response).

---

## 9. Live camera pipeline (webcam or sample video)

```powershell
python scripts/live_camera_pipeline.py --source video
# or for your own webcam:
python scripts/live_camera_pipeline.py
```
Then open **http://localhost:3000/glasses**, switch to **Live Camera** mode. You should see the annotated feed with real-time hazard score, PPE status, and fall detection.

**Offline resilience test:** disable your network mid-run (or point `--api` at an unreachable host) — events should queue locally (`data/offline_queue.db`) and drain automatically once connectivity returns. Check the on-screen `OFFLINE-QUEUE:N` counter.

---

## 10. Backend feature checks (curl)

```powershell
# Compliance validation -> creates a real linked FieldIssue + notifies
curl -X POST http://127.0.0.1:8000/api/v1/compliance/validate -H "Content-Type: application/json" -d '{
  "observation_id":"test-1","asset_id":"asset-42","zone_id":"A12",
  "measurement":{"parameter":"spacing","measured_value":190,"unit":"mm","confidence":0.9},
  "specification":{"spec_id":"s1","expected_value":150,"tolerance_min":140,"tolerance_max":160,"unit":"mm","standard_ref":"ACI 318-19"}
}'
# Expect result: FAIL, severity: CRITICAL, and a field_issue_id in the response

# Confirm it actually landed in the DB:
curl http://127.0.0.1:8000/api/v1/projects/default-project/issues
curl http://127.0.0.1:8000/api/v1/notification/active

# Confirm it ALSO landed in the Knowledge Graph (Asset + Inspection nodes,
# LOCATED_IN/INSPECTS edges — agents/knowledge_graph/writer.py, written on
# every PASS/FAIL/UNCERTAIN validation, not just FAIL):
curl "http://127.0.0.1:8000/api/v1/graph/full?project_id=default-project"
# Expect an "asset" node for asset-42 with latest_inspection_result: "FAIL"

# Learning agent — resolve an incident, check it writes to all 3 stores
curl -X POST http://127.0.0.1:8000/api/v1/learning/resolve -H "Content-Type: application/json" -d '{
  "incident_id":"test-incident-1","project_id":"default-project","zone_id":"A12",
  "asset_type":"rebar","issue_type":"spacing_violation","measurement_at_detection":190,"spec_value":150,
  "resolution":{"action_taken":"repositioned","time_to_resolve_hours":2.5,"resolved_by":"E-005","rework_required":false},
  "outcome_metrics":{"cost_avoided_usd":12000}
}'
# Expect: {"storage": {"postgresql":{"success":true}, "neo4j":{"success":true}, "qdrant":{"success":true}}}

curl http://127.0.0.1:8000/api/v1/learning/stats
curl http://127.0.0.1:8000/api/v1/learning/trends
curl http://127.0.0.1:8000/api/v1/learning/recent-incidents

# Knowledge Graph — unified Postgres (Project/Zone/Issue) + Neo4j (Incident/Engineer) payload behind the /graph page
curl "http://127.0.0.1:8000/api/v1/graph/full?project_id=default-project"
# Expect real zone/issue nodes always; an "incident" + "engineer" node appears
# once you've run the /api/v1/learning/resolve call above at least once

# Version Control — real commit/history (Neo4j AssetVersion nodes), replacing
# the old fixed-hash/2-row-hardcoded stub
curl -X POST http://127.0.0.1:8000/api/v1/version-control/commit -H "Content-Type: application/json" -d '{"asset_id":"asset-rebar-42","changes":{"note":"Repositioned rebar to 152mm"},"author":"E-005"}'
curl http://127.0.0.1:8000/api/v1/version-control/history/asset-rebar-42
# Expect a distinct commit_hash each call, and history growing with each commit

# Zone-scoped cross-worker hazard broadcast — open the Glasses Feed page
# (/glasses) in two browser tabs, both set to Zone A12 (default), open a
# third tab set to a different zone (edit the zoneId prop/URL if exposed,
# or use the WebSocket test below). Trigger a HIGH/CRITICAL compliance FAIL
# for A12 (§10's compliance/validate curl) and confirm:
#  - Both A12 tabs show the amber/red "Zone A12 advisory" banner + a toast
#  - A tab on a different zone shows nothing
# Or test the isolation directly over WebSocket (requires `pip install websockets`):
python -c "
import asyncio, websockets, requests
async def main():
    async with websockets.connect('ws://127.0.0.1:8000/ws/zone/A12') as a12, \
               websockets.connect('ws://127.0.0.1:8000/ws/zone/B3') as b3:
        await asyncio.sleep(0.5)
        requests.post('http://127.0.0.1:8000/api/v1/compliance/validate', json={
            'observation_id':'t1','asset_id':'a1','zone_id':'A12',
            'measurement':{'parameter':'spacing','measured_value':250,'unit':'mm','confidence':0.95},
            'specification':{'spec_id':'s1','expected_value':150,'tolerance_min':140,'tolerance_max':160,'unit':'mm','standard_ref':'ACI 318-19'}
        })
        print('A12:', await asyncio.wait_for(a12.recv(), timeout=5))
        try:
            print('B3 (should timeout):', await asyncio.wait_for(b3.recv(), timeout=2))
        except asyncio.TimeoutError:
            print('B3: nothing received (correct)')
asyncio.run(main())
"

# RAG / project memory — ingest the OSHA PDF, then ask real questions
python scripts/ingest_spec.py
curl "http://127.0.0.1:8000/api/v1/memory/stats?project_id=default-project"
# Expect indexed_passages > 0 after the ingest step above, and llm_configured
# reflecting whether LLM_BACKEND is set to something other than "mock"
curl -X POST http://127.0.0.1:8000/api/v1/memory/query -H "Content-Type: application/json" -d '{"query":"At what height must fall protection be provided?","project_id":"default-project","zone_id":"A12","worker_id":"W-001"}'
# With LLM_BACKEND=groq: a real cited answer referencing the OSHA document.
# Without it: answer is null and evidence[] contains the real matching OSHA
# passages verbatim — never a fabricated narrative either way.
```

---

## 11. Optional API keys (unlocks fuller functionality — the app runs without them, just degrades gracefully)

Add to `.env` at the repo root:

```
GROQ_API_KEY=your_key_here       # real Whisper STT + LLM chat (Memory Q&A, Predictive RFI)
GEMINI_API_KEY=your_key_here     # real server-side TTS + VLM scene understanding + drawing OCR (version control)
LLM_BACKEND=groq                 # so Predictive RFI (Agent 6) / Memory Q&A use a real LLM instead of the honest no-LLM fallback
```

Note: VLM scene analysis (`agents/vision/vlm_analyzer.py`) and drawing-title-block OCR (`agents/version_control/scanner.py`'s `GeminiOCR`) both run on Gemini, not Groq — Groq decommissioned every vision-capable model on this project's account, confirmed live against `/v1/models`, so both were switched to Gemini (which the project already needs a key for, for TTS).

Restart the backend after changing `.env`.

**Test Gemini TTS directly:**
```powershell
python -c "
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv()
from agents.voice.tts import synthesize_speech
result = synthesize_speech('Warning. Stop work.')
print('Got audio:', result is not None, 'length:', len(result or ''))
"
```

---

## 12. Frontend — page-by-page checklist

Log in, then visit each page. All should load without a browser console error:

| Page | What to check |
|---|---|
| `/` Command Center | Live site map with real zone risk scores, active issues panel, RFI predictions |
| `/executive` | KPI bar shows LIVE badge (not DEMO) once `/learning/stats` has data; charts and ROI calculator's "Actual results so far" panel populate |
| `/glasses` | Demo Scenarios (canned, explicitly labeled), Live Camera (real, needs §9), Webcam/Upload in demo mode (real VLM call) |
| `/zones` | Real zone cards, "Alert Team" button, "Details" side panel |
| `/issues` | Resolve/Escalate modals attribute actions to your logged-in name, not "current_user" |
| `/rfis` | "Refresh Analysis" calls the real predictor per zone; "View Similar Historical RFIs" jumps to Project Memory with the query pre-filled |
| `/drawings` | Upload a real PDF — get back a real indexed-chunk count |
| `/memory` | Ask a real question — shows a synthesized AI answer if `LLM_BACKEND` is configured, otherwise the real retrieved passages with an honest "no AI synthesis" banner (no fabricated answer either way); knowledge-base stat strip shows real indexed-passage count; zone scope selector, example queries, recent-search chips (needs §10's ingest step for results) |
| `/notifications` | Real audit-log rows once a CRITICAL/HIGH event has fired (§10); severity stat cards, search/filter, per-channel delivery breakdown (delivered/failed/simulated), expandable dispatch detail with per-channel timestamps and error text, auto-refreshes every 20s |
| `/graph` | Interactive node-link graph — Postgres Project/Zone/Issue + real Neo4j Incident/Engineer (from resolved incidents) + real Neo4j Asset/Inspection nodes (written on every compliance validation, colored by latest PASS/FAIL/UNCERTAIN result, §10); drag nodes, scroll to zoom, search/filter by type, click a node for its real properties in the side panel |
| `/twin` | 3D site model with real structural dressing (slabs/columns/scaffold levels) per zone; worker-count markers (🧍 × active_worker_count, hover for tooltip), pulsing hazard beacons per real open issue (click to highlight in the zone panel), Jarvis-style HUD overlay (corner brackets, live clock, real worker/issue/critical-zone stats), scan-sweep animation |

**Role-based nav check:** log out, log in as `worker@fieldpilot.demo` — the sidebar should show only Command Center, Glasses Feed, and Project Memory. Log in as `admin@fieldpilot.demo` — everything should be visible.

---

## 13. Mobile app (worker app — `frontend/mobile/`)

```powershell
cd frontend/mobile
npm install
npx expo start
```
Scan the QR code with Expo Go (Android/iOS), or press `w` for the web preview.

### 13.1 The backend must be reachable from the phone

Two things trip this up, and both look identical from the phone (every request just fails):

**a) Bind the API to all interfaces, not loopback.** `--host 127.0.0.1` is reachable only from the laptop itself:

```powershell
cd api
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**b) Let Windows Firewall through** on first run — accept the prompt, or:

```powershell
New-NetFirewallRule -DisplayName "FieldPilot API" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

Verify from the phone's browser before touching the app: open `http://<your-lan-ip>:8000/api/v1/health`. If that doesn't return JSON, no amount of in-app configuration will help.

```powershell
# your LAN IP
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' }).IPAddress
```

**The API URL is now auto-detected** — `src/config.ts` reads the Metro bundler's host, which is by definition your dev machine as reachable from that phone. It prints the resolved URL to the Expo console on startup:

```
[FieldPilot] API base URL: http://192.168.1.42:8000
```

That covers physical phones (LAN IP), the Android emulator (`10.0.2.2`) and the iOS simulator (`localhost`) with no per-device configuration. Override it in **PROFILE → API Base URL** (persisted), or bake in `EXPO_PUBLIC_API_URL` for a standalone build.

### 13.2 Tab-by-tab

| Tab | What to check |
|---|---|
| SCAN | Grant camera permission, tap capture — real photo to `POST /api/v1/vision/understand`, real PASS/FAIL/STOP-WORK overlay. Also appends a row to History. |
| ISSUES | Real list from `GET /api/v1/projects/default-project/issues` |
| HISTORY | **Real** — `GET /api/v1/interactions`, showing every scan, voice query and measurement with its verdict, agent chain and latency. Pull to refresh. Empty on a fresh database until you do something; that empty state is labelled distinctly from a connection failure. |
| VOICE | Tap mic, speak → real Whisper transcription + Gemini TTS playback via `POST /api/v1/voice/query` (multipart). Check `GET /api/v1/voice/status` first to confirm STT/LLM/TTS are all configured. |
| ASK AI | Real `POST /api/v1/memory/query`; shows a synthesized answer or the real raw passages with an honest note — never a fabricated answer |
| PROFILE | Persists API Base URL / Gemini key to AsyncStorage |

### 13.3 Verifying the audit trail

Everything the worker does lands in one queryable feed:

```powershell
curl "http://127.0.0.1:8000/api/v1/interactions?limit=20"
curl "http://127.0.0.1:8000/api/v1/interactions/stats"
```

Expect rows like `A2:Measurement -> A5:Compliance -> A9:Notify` with real latencies. A measurement the system *refused* to make records as `UNCERTAIN` rather than disappearing — that is deliberate, and worth pointing out to a judge as evidence the system doesn't hide its own uncertainty.

### 13.4 Expo SDK note

The app is on **SDK 54**. `frontend/mobile/AGENTS.md` points at the **v57** docs, and two dependencies do not survive that upgrade:

- **`expo-av` is removed in SDK 57** (replaced by `expo-audio` / `expo-video`). `VoiceScreen.tsx` uses `Audio.Recording` and `Audio.Sound`, and `app.json` declares the `expo-av` plugin for the microphone permission. All three need migrating before moving to 57.
- **`expo-file-system` was imported but never installed** — `VoiceScreen` could not bundle at all. Removed: the recording now uploads as multipart FormData, which React Native streams natively from a `file://` URI and which needs no filesystem library on either SDK.

`expo-camera`'s API (`CameraView`, `useCameraPermissions`, `takePictureAsync({ base64 })`) is unchanged between 54 and 57, so the SCAN tab needs no work.

---

## 14. Known environment-dependent gaps (not bugs — see `FieldPilot AI_Remaining_Execution_Plan.md` for the full list)

- **No `GROQ_API_KEY`/`LLM_BACKEND=groq`** → Predictive RFI and Memory Q&A fall back to honest no-LLM responses (real retrieved data, no synthesized narrative) instead of crashing or fabricating. Add the key + backend setting to unlock real LLM synthesis.
- **Neo4j write-paths are partial** → Zone/Asset/Inspection/Incident/Engineer/AssetVersion nodes are now real (written by compliance validation, the Learning Agent, and Version Control commits), but `RFI`/`Drawing`/`Project`/`Specification` nodes still have no live write-path — only `scripts/seed_demo_data.py` creates those, and it isn't run automatically.
- **No real Slack/Twilio credentials** → notifications dispatch through a real routing/audit pipeline but the actual channel sends are simulated (clearly marked `mock_channels` in the API response and in the Notifications page UI).
- **Drawings table (web dashboard) is still mock data** — no "list all drawings" backend endpoint exists yet; upload itself is real.
- **Predictive RFI runs on the scorecard, not a trained model** — `GET`/`POST` responses report `scoring_mode: "scorecard"`. The probability is computed from real database features via an explicit logistic model whose weights are stated in `agents/predictive_rfi/risk_model.py`; it switches to `"trained"` once `models/training/train_rfi_predictor.py` has enough resolved history to fit on (60+ windows, 12+ positives) and `RFI_MODEL_PATH` is set. Both modes are real; the mode is always reported.
- **Vision runs on stock COCO YOLO11n** until training job T1 completes — it detects `person` but not `rebar`/`conduit`/`formwork`. See `docs/TRAINING_PLAN.md`.
- **Measurement needs a scale reference.** With no ArUco marker, no known reference object, and depth disabled, `POST /api/v1/measurement/*` returns `status: "uncalibrated"` and refuses to guess. That is correct behaviour, not a failure — print the marker (`GET /api/v1/measurement/marker`, or `python models/training/make_aruco.py`) at 100% scale.

### 14.1 Running with infrastructure down

The system is expected to stay usable when Docker isn't running. Verified behaviour:

| Endpoint | Neo4j/Qdrant down |
|---|---|
| `GET /graph/zone/{id}/status` | `200` + `status: degraded, source: postgres` — real zone data, never invented |
| `GET /graph/project/{id}/zones` | same (this previously served three **hardcoded fake zones** that rendered identically to live data) |
| `POST /memory/query` | `200` + `status: degraded` with `error_class: store_unreachable`, and **no** fabricated answer |
| `POST /measurement/validate` | fully functional — measurement needs no database |
| `GET /interactions` | `200` + degraded, empty feed with the reason attached |

Measured end-to-end `measure → validate` with every database stopped: **~2.3s**, inside the <5s budget. A circuit breaker stops retrying a known-down Neo4j and half-opens to recover on its own, so bringing Docker up mid-demo needs no restart.

---

## 15. Shutting everything down

```powershell
# Ctrl+C in the uvicorn and npm run dev terminals, then:
docker compose down
```
(Add `-v` to also wipe the Postgres/Qdrant/Neo4j volumes if you want a completely clean slate next time — this deletes all seeded/test data.)
