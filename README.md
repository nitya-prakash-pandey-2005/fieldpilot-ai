# FieldPilot AI 🚀

FieldPilot AI is an advanced, multi-agent AI system designed to monitor construction sites in real-time using Meta Smart Glasses. It passively detects hazards, measures rebar spacing, compares real-world data against BIM models, and automatically drafts RFIs (Requests For Information) without the worker ever having to pull out a tablet or take off their gloves.

## 🏗️ The Problem We Solve
Construction delays and rework cost the industry billions of dollars annually. Current inspection software requires manual photos and tedious form-filling. 

FieldPilot AI solves this through a **10-Agent Workflow**:
- **Agent 1 (Vision):** Ingests live frames from Meta Glasses.
- **Agent 2 (Measurement):** Uses depth estimation to calculate millimeter-accurate spacing (e.g., rebar).
- **Agent 3 (Compliance):** Compares physical measurements against the digital BIM model.
- **Agent 4 (Safety):** Detects PPE compliance (hard hats, vests) and trip hazards.
- **Agent 5 (Voice NLP):** Processes natural language voice queries from the worker.
- **Agent 6 (RFI Drafter):** Automatically generates RFIs for engineer approval if a deviation is found.
- **Agent 7 (Knowledge):** Looks up exact PDF specs and building codes via RAG.
- **Agent 8 (Notification):** Sends critical alerts to the dashboard or WhatsApp.
- **Agent 9 (Memory):** Logs the incident into a Neo4j Knowledge Graph.
- **Agent 10 (Learning):** Analyzes historical graphs to predict *future* RFIs before they happen.

## 📱 Hardware & Edge Architecture

### The "Mobile Phone Relay" & Offline Mode
While workers wear the Meta Glasses, they do not hold a phone. The phone stays in their pocket acting as a **Mobile Edge Node**. 
- The glasses connect to the pocketed phone via Bluetooth. 
- The FieldPilot mobile app acts as the secure bridge to the cloud.
- **No WiFi? No Problem:** Construction sites often lack internet. We deploy lightweight, quantized AI models (like YOLOv9-tiny for safety) directly on the smartphone's Neural Processing Unit (NPU). It processes hazards locally and gives immediate Text-to-Speech (TTS) audio warnings back to the worker through the glasses' open-ear speakers.
- **Store and Forward:** When the worker re-enters a WiFi zone, the pocketed phone batch-syncs the cached incidents to the cloud.

*(Note: The mobile version of the app uses Expo Go 54.0.0. Currently, the live tunneling functionality is under maintenance, but the core architecture remains intact for edge processing).*

### Location Tracking (400+ Workers)
We do not rely on inaccurate indoor GPS. Instead, we use cheap Bluetooth Low Energy (BLE) beacons attached to concrete pillars around the site. The phone in the worker's pocket triangulates the nearest beacon and automatically tags the live video feed with the correct Zone ID (e.g., "Zone A12"). 

## 🌐 The Command Center Web Dashboard
Site managers cannot see through 400 pairs of glasses at once. The web dashboard acts as the central command hub:
- Engineers review auto-drafted RFIs and approve design deviations.
- Executives view ROI analytics (cost saved, RFIs avoided).
- **Live 3D Site Map:** By aggregating video feeds from all workers, the cloud reconstructs the site in 3D (via NeRF/Gaussian Splatting) and overlays it onto the digital BIM model. Discrepancies glow red in real-time.

---

## 🚀 How to Run the App Locally

To run the complete system, you need to start the Backend (FastAPI), the Engineer Dashboard (Next.js), and the Executive Dashboard (Next.js) concurrently.

### 1. Backend (FastAPI)
The backend powers the 10-Agent orchestration, handles the PostgreSQL database, and streams real-time data via Server-Sent Events (SSE).

```bash
cd api
pip install -r requirements.txt
python -m uvicorn main:app --reload
```
*The API will be available at `http://localhost:8000`*

> **No Postgres?** The API detects that at startup and falls back to SQLite at
> `api/fieldpilot.db`, seeding every table. Run `python scripts/verify_system.py`
> to see exactly which services are live and which are degraded — it reports
> `PASS` / `DEGRADED` / `FAIL` per agent rather than a single health boolean.

### 1b. Metric measurement engine (`measure/`)

Agent 2's object-dimensioning half is backed by `measurecv`, a self-contained
metrology package in this repo (RT-DETR → SAM 2 → Metric3D, Apache-2.0).

```bash
pip install -e "./measure[models,api]" timm mmengine
```

Weights (~500 MB for the CPU preset) download on first use. Without them,
dimensioning reports `status: "unavailable"` and the ArUco/reference spacing
path continues to work — no numbers are ever invented to fill the gap.

See **[docs/MEASUREMENT_INTEGRATION.md](docs/MEASUREMENT_INTEGRATION.md)** for
the two-engine split, the uncertainty-aware verdict rule, and how far the
numbers can actually be trusted (uncalibrated ≈ 15%, calibrated 1–2%).

### 2. Engineer Dashboard (Next.js)
This is the primary operational dashboard for reviewing active issues, the 3D site map, and predictive RFIs.

```bash
cd frontend/engineer-dashboard
npm install
npm run dev
```
*The Engineer Dashboard will be available at `http://localhost:3000`*

### 3. Executive Dashboard (Next.js)
This dashboard provides high-level ROI metrics, cost avoidance stats, and system health.

```bash
cd frontend/executive-dashboard
npm install
npm run dev
```
*The Executive Dashboard will be available at `http://localhost:3001` (or whichever port Next.js assigns if 3000 is taken).*

---

### 📲 Mobile App (Expo Go)
If you wish to run the mobile app locally (Note: Tunneling currently has issues):
```bash
cd frontend/mobile
npm install
npx expo start
```
Scan the QR code with the Expo Go app (SDK 54.0.0) on your mobile device.

---

## 🔌 Hardware we do not have, and what stands in for it

No Meta glasses, no BLE beacons, no phone NPU were available for this build. Each
substitution is listed here and labelled in the UI rather than left implied.

| Pitch hardware | Substitute | Where it says so |
|---|---|---|
| Meta glasses camera/mic/speaker | Browser `getUserMedia` on a laptop or phone | `/glasses` header reads **"Glasses Mode · SIMULATED VIA DEVICE CAMERA"** |
| Bluetooth glasses→phone relay | Removed — camera, mic and speaker are already on one device | this table |
| BLE beacons for zone ID | Trilateration is **real** (`agents/localization/rssi.py`); with no physical beacons the RSSI it solves comes from `scripts/ble_simulator.py` | simulator docstring; it models the radio, never the answer |
| Phone NPU | `onnxruntime` on laptop CPU. Provider selection for NNAPI/CoreML/QNN is implemented but **cannot be exercised on a desktop build** | `GET /api/v1/edge/status` returns that caveat in its `note` field |

Follow.md §3 suggested QR-code zone tags as the beacon substitute. We kept the
BLE trilateration path instead, because it was already built and it exercises the
real solver — distance smoothing, multilateration, zone assignment — rather than
reducing zone identity to a scanned string. The trade is that zone positions in a
demo are simulator-fed unless real beacons are deployed, and the server cannot
tell the difference by design.

The demo scenarios on `/glasses` carry a **SIMULATED** banner: those figures
(152 mm, 97 %, 2.3 s) are fixed illustrative values for walking through the
workflow, not model output. Live Camera and Agent Flow are the real paths.

---

## 🧠 Watching the swarm run (`/architecture`)

The ten agents are wired together as a real LangGraph `StateGraph`
(`agents/orchestrator/graph.py`) — one node per agent, conditional edges for
"deviation found? → draft an RFI", and a deferred join so Measurement and Hazard
can run in parallel and still converge exactly once.

Open **Agent Flow** in the dashboard, capture a frame, and watch each node light
up as it actually fires. The diagram is generated from
`GET /api/v1/orchestrator/graph`, which is built from the same structures the
graph is compiled from, so it cannot drift from what executes. Node states are
`fired` / `skipped` / `failed` — a skipped agent shows the reason it skipped
rather than disappearing.

```bash
curl -X POST http://localhost:8000/api/v1/orchestrator/run \
  -H "Content-Type: application/json" \
  -d '{"frame_b64": "<base64 JPEG>", "mode": "cloud", "zone_id": "A12"}'
```

### Cloud vs Offline/Edge

The mode toggle swaps the models, not a label. Measured on the same frame, on
this laptop:

| | Cloud | Offline / Edge |
|---|---|---|
| Detector | YOLO11n + PPE + pose (PyTorch) | YOLO11n-pose INT8 (onnxruntime) |
| Vision time | ~7 s | **0.7–1.2 s** |
| Depth | Metric3D via `measurecv` | disabled — ~5.6 s/frame is not an on-device budget |
| Hazards | pose + PPE fusion (found 4 PPE violations) | geometric rules only (found none) |
| Speech out | Gemini TTS | **Kokoro-82M, on device** |
| Total run | ~22 s | **~5.8 s** |

Edge mode never falls back to a cloud call. If the local model is missing it
says so and stops — quietly reaching for the network would make the offline demo
prove the opposite of what it claims. The capability gap is real and shown in the
UI: the on-device rules genuinely do not catch PPE violations.

Edge TTS needs Kokoro's weights (~340 MB, not in the repo):

```bash
curl -L -o models/weights/kokoro-v1.0.onnx  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o models/weights/voices-v1.0.bin   https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

### The spec corpus (Agent 7) — no Docker required

Qdrant runs embedded when no container is reachable, against `data/qdrant_local`
(Follow.md §4's "local mode to avoid a Docker dependency during the demo").
Retrieval quality is identical — same index, same embeddings, in-process. The
only constraint is that embedded storage takes an exclusive directory lock, so
one process at a time holds it; that is why ingestion goes over HTTP.

```bash
# with the API running:
python scripts/ingest_spec.py
```

That indexes **1741 passages** from two sources, and the distinction between
them is stamped on every citation:

| Source | What it is | Provenance |
|---|---|---|
| OSHA 3146, 2202, 3150 (868 chunks) | Fall protection, industry digest, scaffold use | **Real** public-domain US government publications |
| `data/project_documents.json` (5 records) | Drawing S-101 R5, RFI-2024-0089, CO-047, inspections | **Synthetic** — every `source` carries `(demo project record)` |

The suffix travels into every drafted RFI and every spoken answer, so an
engineer can tell a published standard from this project's own paperwork without
going digging. Nothing invents a clause: if no passage clears the similarity
threshold, Agent 7 returns zero citations and Agent 6 marks the RFI **uncited**
rather than writing a plausible-sounding one.

A verified deviation → RFI run, end to end:

```
ok  2. Measurement       205.1mm via aruco          (ArUco calibration, ±1–2mm)
ok  3. Compliance        FAIL: 205.1mm vs 150.0mm [140–160]   spec SPEC-REBAR-A12
ok  7. Knowledge         1 clause retrieved (0.83)  S-101-R5.pdf (demo project record)
ok  6. RFI Drafter       drafted with 1 citation
ok 10. Learning          zone A12: spacing_deviation recurred 3x in 30 days
```

### Specs are stored, not supplied

Agent 3 resolves its tolerance from `data/specs.json` via
`agents/compliance/spec_registry.py`. If no spec matches, it returns `no_spec`
and withholds the verdict rather than assuming a tolerance — a guessed tolerance
produces a PASS/FAIL indistinguishable from a real one.

---

## ⚖️ Model licences

| Component | Model | Licence |
|---|---|---|
| Agents 1 & 4 (detection, PPE, pose) | Ultralytics YOLO11n | **AGPL-3.0** |
| Agent 4 edge runtime | YOLO11n-pose INT8 ONNX (Ultralytics export) | **AGPL-3.0** |
| Agent 2 depth | Metric3D | BSD-2-Clause |
| Agent 2 detection/segmentation | RT-DETR, SAM 2 | Apache-2.0 |
| Agent 8 offline TTS | Kokoro-82M | Apache-2.0 |
| `measure/` (`measurecv`) | — | Apache-2.0 |

**The Ultralytics models are AGPL-3.0.** That is a copyleft licence with a
network clause: shipping this as a hosted service commercially requires either
releasing the source under AGPL or buying an Ultralytics Enterprise licence.
Everything else in the stack is permissive. Swapping the detector for RF-DETR
(Apache-2.0) would clear it; that has not been done, so the obligation stands
and is recorded here rather than left for someone to discover.

---

## 🌟 Unique Selling Points
- **Passive "Hands-Free" Inspection:** Workers keep their gloves on and tools in hand. The AI watches and files paperwork automatically.
- **Predictive Analytics:** Our Knowledge Graph predicts where the next deviation will happen based on historical site trends.
- **Edge-NPU Processing:** True zero-latency safety alerts by utilizing the pocketed smartphone's AI chip.
