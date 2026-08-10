# MASTER BUILD PROMPT — FieldPilot AI (Stage 3 Qualification Build)

> **How to use this file:** Paste this entire document as your first message to Claude Code (or a Claude session with computer/file access) inside your project folder. It is written *to* that agent, in second person. Do not summarize it back to the user before starting — act on it directly, starting with Phase 0.

---

## 0. YOUR ROLE AND THE STAKES

You are the lead engineer finishing **FieldPilot AI** — "the hands-free digital foreman for the physical world" — for a hackathon Stage 3 qualification. Judges will evaluate **whether what the team pitched is actually implemented**, feature by feature, not whether the pitch deck sounds good. That means:

- Every claim in the pitch deck below needs a corresponding, runnable, non-mocked feature — or an honest, visible "not yet implemented" state. **Never fake a result to look finished.** A judge clicking around and finding hardcoded numbers where a model should be running is worse than an honestly smaller but real system.
- The team does not have physical Meta smart glasses. **Substitute a laptop/phone camera + microphone + speaker** for the glasses, end-to-end, and make that substitution obvious and intentional in the UI ("Glasses Mode: Simulated via Device Camera") rather than hidden.
- The team already has a **Gemini API key** provisioned. Use it as the cloud reasoning path; pair it with real open-source models for the offline/edge path, because the pitch's core differentiator is the offline "Store-and-Forward" story — you should actually be able to demo that, not just claim it.

---

## 1. PHASE 0 — AUDIT BEFORE YOU BUILD (mandatory, do this first)

Before writing or changing any code:

1. Recursively explore the current working directory and any connected repo. List every file, framework, and dependency already present.
2. For each of the 10 agents, each dashboard page, and each infra component listed in Sections 4–8 below, classify it as: **✅ Implemented & working**, **🟡 Stubbed/partial**, or **❌ Not started**. Actually run what exists (start the dev server, hit the API, open the dashboard) rather than inferring status from file names.
3. Note: the live demo URL in the deck (`fieldpilot-ai-ovzd-xur5fuci3.vercel.app`) currently returns a Vercel login wall when fetched externally — treat it as inaccessible for audit purposes and rely on the local repo instead. If you find a different/updated deployment URL in the repo's config, note it but still verify against local source, not the hosted page.
4. Produce a short written audit report (a markdown table is fine) before touching Section 9's build order. Only after that audit do you decide what to build vs. finish vs. leave stubbed given the remaining time.
5. Re-run this audit mentally after each major milestone — don't let "already built" assumptions go stale mid-build.

---

## 2. WHAT FIELDPILOT AI IS (distilled from the pitch deck)

**Problem:** Site engineers work gloved, tooled-up, and mid-task; every time they stop to photograph a deviation, fill a form, or check a blueprint, physical progress stops. Rework from undetected deviations and slow RFI (Request for Information) cycles cost the industry heavily.

**Solution:** A passive, hands-free "digital foreman." Smart glasses watch what the worker sees; the system measures spacing/deviations in real time, cross-references BIM/spec data, catches missing PPE and hazards, auto-drafts the RFI with the spec cited, and speaks the verdict back to the worker's ear — no screen, no typing.

**Why it's supposedly new:** existing tools (Procore, Autodesk) make the worker do the inspecting and reporting. FieldPilot does it *for* them, passively, and aims to predict the next deviation before it happens.

**The 10-agent swarm (from your architecture diagram):**

| # | Agent | Job |
|---|-------|-----|
| 1 | Vision Ingestion | Receives frames, extracts objects/bounding boxes/scene context |
| 2 | Measurement | Depth/distance estimation for real-world spacing |
| 3 | Compliance | Compares Agent 2's measurements against the spec/BIM |
| 4 | Hazard/Safety | Scans for missing PPE, fall hazards |
| 5 | Voice/NLP | Transcribes and parses the worker's spoken queries |
| 6 | RFI Drafter | Auto-drafts an RFI when Agent 3 flags a deviation |
| 7 | Knowledge Retrieval | RAG lookup of the exact spec/code clause |
| 8 | Notification | Routes alerts to the dashboard and back to the worker (TTS) |
| 9 | Project Memory | Logs the incident into a knowledge graph |
| 10 | Learning/Predictive | Learns from history to predict future deviations |

**Data flow (from the diagram you were given, reproduced logically):**
`Glasses ⇄ Pocket Phone Edge Node` (video/audio down over Bluetooth, audio feedback up) → `Pocket Phone → Cloud Ingestion Layer` (WebRTC/RTMP) → Cloud splits into two lanes: **vision** (`Agent1 → Agent2 → Agent3`, with `Agent1 → Agent4` running in parallel) and **voice** (`→ Agent5 → Agent7`) → `Agent3`/`Agent4`/`Agent7` feed `Agent6` (RFI drafting) and `Agent8` (Notification) → `Agent6 → Agent9`, `Agent8 → Agent9` (memory) → `Agent9 → Agent10` (predictive learning) → `Agent8` also closes the loop with a **TTS audio alert back to the pocket phone**, which plays it to the worker.

Your job is to make this exact loop real and demoable, with the phone/laptop camera+mic+speaker standing in for the glasses.

---

## 3. HARDWARE SUBSTITUTION SPEC (glasses → device camera)

Meta Glasses are unavailable. Build the "edge node" as a **web app that runs on any phone or laptop browser** and plays the glasses' role directly:

| Pitch component | Real hardware (unavailable) | Your substitution |
|---|---|---|
| Glasses camera/mic | Meta Smart Glasses | Browser `getUserMedia` (rear camera preferred on phone) capturing frames at a controllable interval |
| Glasses open-ear speaker | Bone-conduction speaker | Browser `<audio>` autoplay of the TTS response (phone speaker or earbuds) |
| Bluetooth relay to pocket phone | N/A | Not needed — camera/mic/speaker are already on the same device, so simplify this hop away and say so explicitly in the architecture page |
| Pocket phone → Cloud (WebRTC/RTMP) | — | Real WebRTC (or simple chunked frame POSTs over `fetch`, which is far easier to get reliably working in a hackathon timeframe — prefer this unless you have time budget for real WebRTC) to your FastAPI backend |
| BLE beacons for indoor zone ID | Physical BLE beacons | **QR-code zone tags**: print/display a QR code per "zone" (e.g., Zone A12), the worker points the camera at it once, the frontend decodes it client-side (e.g., a lightweight JS QR reader) and tags the session with that zone. This is a legitimate, honestly-labeled substitution — present it as "Zone tagging (BLE beacon simulation via QR)" in the UI, not as literal beacon hardware |
| Phone NPU (on-device inference for offline safety) | Snapdragon/Apple NPU | Your laptop's CPU/GPU running the small quantized open-source models from Section 5, gated behind an explicit **"Offline / Edge Mode"** toggle in the UI |

Build a single **"Worker View"** page: camera preview, a mic button, a big "connected / offline" indicator, and a running transcript of what the system says back. This is the whole demo experience of "being the worker."

---

## 4. SYSTEM ARCHITECTURE

- **Orchestration:** LangGraph (Python). It models exactly the directed-graph, stateful, conditional-branch structure the pitch diagram already draws — use it as a literal `StateGraph` with one node per agent, conditional edges for "deviation found? → route to Agent 6" and "hazard found? → route to Agent 8", and built-in checkpointing so a run's state is inspectable (useful both for the offline sync story and for judge demos of "show me what the agent saw").
- **Backend:** FastAPI (Python), async, one ingestion endpoint for frames, one for audio.
- **Frontend:** Next.js + React, two apps or two routes: `/worker` (the camera/mic/speaker device view) and `/dashboard` (the command center from slide 06).
- **Realtime updates to dashboard:** Server-Sent Events (SSE) from FastAPI, as the deck specifies — simpler and more reliable than WebSockets for a one-way event feed, and it's literally what the deck says they used.
- **Vector DB (RAG over specs/codes):** Qdrant (Docker or in-memory `qdrant-client` local mode — use local mode to avoid a Docker dependency during the demo unless Docker is already confirmed working in the audit).
- **Knowledge graph (Project Memory):** Neo4j Community Edition (free), or if you determine in Phase 0 there's no time/appetite to run a Neo4j instance, a graph modeled in-process with `networkx` and persisted to SQLite/JSON — be explicit in the audit and README about which you chose and why, don't silently downgrade.
- **Reasoning split — cloud vs. edge (this is your best demo moment):** build a literal toggle. In **Cloud Mode**, multimodal reasoning and RAG synthesis go through the Gemini API. In **Offline/Edge Mode**, the same agent graph runs against local quantized open-source models. Flip the toggle live during the demo and show the system keep working — this directly proves the pitch's "No-WiFi Construction Site Problem" solution instead of just asserting it.

---

## 5. MODEL & TOOL SELECTION PER AGENT

Research below reflects the open-source landscape as of **August 2026** — verify current versions/links before pinning dependencies, since this space moves fast.

| Agent | Task | Primary (cloud, you already have the key) | Open-source (offline/edge path) | Why |
|---|---|---|---|---|
| 1. Vision Ingestion / object & PPE detection | Real-time object detection | Gemini 3.6 Flash (multimodal) for scene description | **RF-DETR** (Apache-2.0, first real-time detector to break 60 mAP on COCO, DINOv2-backed so it fine-tunes fastest to a new domain like a construction site) as primary; **YOLO26n** as a CPU-friendly fallback if RF-DETR is too heavy on the dev laptop | RF-DETR's whole selling point is fast domain adaptation with little data — ideal for a hackathon fine-tune window; YOLO26 is the pragmatic edge fallback |
| 2. Measurement (depth) | Monocular depth → real-world spacing | Gemini 3.6 Flash for rough spatial reasoning/blueprint cross-referencing (it's specifically noted as strong at "visual blueprint conversion" as of the 3.6 release) | **Depth Anything V2** (Small/Base checkpoint for CPU-feasible inference) | Still the most widely deployed, best-documented open monocular depth baseline; V2-Small runs on modest hardware |
| 3. Compliance | Compare measured spacing vs. spec | Gemini 3.6 Flash (structured output mode, JSON schema for pass/fail + delta) | Rule engine in Python comparing Agent 2's output against a parsed spec value, escalate to a local VLM only if ambiguous | Keep this deterministic where you can — judges trust a visible if/else spacing check more than an opaque model call for a task that's fundamentally arithmetic |
| 4. Hazard/Safety (PPE detection) | Missing hard hat/vest/fall hazard detection | — | Same **RF-DETR/YOLO26** detector as Agent 1, fine-tuned on a PPE-labeled dataset (Section 7) with a distinct hazard-class head | Reuse the detector; don't stand up a second model for a near-identical CV task |
| 5. Voice/NLP | Speech-to-text of the worker's spoken query | Gemini 3.6 Flash audio input (simplest integration) | **faster-whisper** (CTranslate2 reimplementation of Whisper, ~4x faster, runs fine on a laptop CPU) using the `large-v3` or `distil-large-v3` checkpoint | faster-whisper remains the pragmatic self-hosted default; keep Gemini as the low-effort cloud path |
| 6. RFI Drafter | Structured RFI document generation with cited spec text | Gemini 3.6 Flash, JSON/structured output | Same local LLM used for Agent 7's synthesis (see below), constrained to a template | RFI drafting is a text-generation + retrieval task, not vision — route it through whichever LLM the current mode (cloud/edge) has selected |
| 7. Knowledge Retrieval (RAG) | Retrieve the exact spec clause for a deviation | Gemini 3.6 Flash for the final synthesis step | **Qdrant** for vector search + a small local instruction model (e.g., a quantized 7–8B Llama/Qwen instruct model via `llama.cpp`/Ollama) for synthesis when offline | Keep retrieval identical in both modes (Qdrant); only swap the generator model |
| 8. Notification | Route alert to dashboard (SSE) + trigger TTS | — | **Kokoro-82M** (Apache-2.0, ~82M params, runs on CPU in real time, no GPU required) for text-to-speech | Kokoro is the standout pick for a laptop demo: small, fast, real-time-capable, and license-clean — you need audio to *actually* play back live, not be pre-recorded |
| 9. Project Memory | Log incident to graph | — | Neo4j Community (or networkx fallback per Section 4) | — |
| 10. Learning/Predictive | Pattern learning across logged incidents | — | Start honest: a simple frequency/co-occurrence analysis over the graph ("this zone has had 3 rebar-spacing deviations this week") rather than claiming a trained predictive model you don't have time to build. Label it clearly as a heuristic in the UI, and note true ML-based prediction as a "Phase 4 roadmap" item — this matches the deck's own roadmap slide, so it's not a gap, it's the plan |

**Multimodal VLM note:** if any agent needs open-ended visual question answering beyond detection (e.g., "does this look like formwork or scaffolding?"), use **Qwen2.5-VL-7B-Instruct** locally (it's the most battle-tested open VLM at a size that fits a single consumer GPU, and it's what the team already has prior experience with) — don't introduce a second unfamiliar VLM under time pressure.

**Do not hand-wave "quantized YOLOv9" or "Llama.cpp 3B" from the original deck's tech-stack slide as if they're locked in.** Use this table's picks; they reflect the current (2026) state of the art and are what you should actually implement. If you deviate, say why in the audit.

---

## 6. TECH STACK SUMMARY

```
Frontend:      Next.js (App Router) + React + Tailwind
Realtime:      Server-Sent Events (dashboard) + fetch-based frame/audio POST (worker device)
Backend:       FastAPI (Python 3.11+), async
Orchestration: LangGraph
Vision:        RF-DETR (primary) / YOLO26n (edge fallback)
Depth:         Depth Anything V2 (Small/Base)
VLM (if needed): Qwen2.5-VL-7B-Instruct (local) / Gemini 3.6 Flash (cloud)
STT:           faster-whisper (distil-large-v3) / Gemini audio input
TTS:           Kokoro-82M
Vector DB:     Qdrant (local mode)
Graph DB:      Neo4j Community / networkx fallback
Cloud LLM:     Gemini API (gemini-3.6-flash as the default workhorse; gemini-3.5-flash-lite if you need cheaper/faster calls for high-frequency classification-style agent steps)
```

---

## 7. REAL DATASETS — DO NOT SIMULATE

The pitch explicitly promises "real data from open source of construction." Deliver on that:

- **PPE/hazard detection training data:** the Roboflow **"Construction Site Safety"** dataset (CC BY 4.0, labels: `Hardhat`, `Mask`, `NO-Hardhat`, `NO-Mask`, `NO-Safety Vest`, `Person`, `Safety Cone`, `Safety Vest`, `machinery`, `vehicle`) — also mirrored on Kaggle. It's annotated, sizeable, and directly matches Agent 4's job. Fine-tune your detector on this rather than a toy set.
- **Rebar/spacing-style CV data:** search Roboflow Universe for "rebar" and "construction hazard" projects (several thousand-image public sets exist) if you have time to fine-tune Agent 1/2's specific spacing-detection behavior; otherwise, demonstrate spacing measurement live on real photos you take yourself during testing rather than a pre-baked example, so the pipeline is provably running, not memorized.
- **Spec/RFI text corpus for RAG (Agent 7):** don't fabricate spec clauses. Load a small set of real public construction standards excerpts (e.g., publicly available building-code or OSHA excerpts, or a public sample specification PDF) into Qdrant, chunk them properly, and cite the actual retrieved clause in the RFI, not an invented one. If you only have time to seed a handful of real documents, that's fine — a small, real, correctly-cited knowledge base beats a large fabricated one.
- **BIM reference:** buildingSMART publishes free sample IFC (Industry Foundation Classes) model files — use one as a stand-in "digital twin" reference for the compliance check rather than inventing spec numbers out of thin air.

---

## 8. DASHBOARD PAGES (make these genuinely useful and good-looking, not just present)

Build these as real, data-driven pages (backed by the SSE feed / API, not mock JSON left in forever):

1. **Live Site Map / Command Center** (deck slide 06) — active zones (from QR tagging), a feed of the current worker's camera view (optional, if time allows), a running list of active issues.
2. **Issues / RFI Queue** — every drafted RFI from Agent 6, showing the cited spec clause, the measured deviation, and an "Approve" button (the deck's "engineer just clicks Approve" promise) — approving should actually change state (e.g., mark resolved in the graph).
3. **ROI / Impact Panel** — build this as a **transparent, adjustable calculator** (inputs: rework cost per deviation, worker hourly rate, deviations caught this session), not a hardcoded restatement of the deck's headline numbers (23 RFIs/month, $1.3M, 340h, 94.3% accuracy). Those are illustrative pitch projections from the deck, not measured results — presenting them as if they were live output from *your* running system would be a fabricated-metrics red flag to any competent judge. Instead, surface your **actual** measured detection accuracy from a real held-out test split of the dataset you fine-tuned on, and let the ROI numbers scale from real session activity.
4. **Architecture / Agent Flow view** — a live-updating version of the diagram you were given: light up each of the 10 agent nodes as they actually fire during a real request, so judges can watch the pipeline execute rather than read about it.
5. **Worker View** (Section 3) — the camera/mic/speaker device page.

Design direction: dark, high-contrast "ops center" aesthetic (the deck already leans this way — "Downtown Tower Phase 2 · ● LIVE"); consistent type scale, real icons, and genuinely legible data density rather than decorative placeholders.

---

## 9. BUILD ORDER (given limited time before Stage 3)

Work in this order; each phase should leave you with something fully demoable, not half of everything:

**Phase 1 — Core loop, cloud-only, one agent path working end to end**
Worker View captures a frame → FastAPI ingests it → Gemini 3.6 Flash does detection + compliance reasoning in one call → a hazard or deviation triggers Agent 8 → Kokoro TTS plays back on the same device. Get this fully working before touching anything else — it proves the whole hands-free loop.

**Phase 2 — Real local models replace the cloud call for vision**
Swap in RF-DETR/YOLO26 fine-tuned on the Roboflow PPE dataset for Agent 1/4, Depth Anything V2 for Agent 2. Add the Cloud/Edge mode toggle.

**Phase 3 — RAG + RFI drafting**
Stand up Qdrant, seed it with real spec text (Section 7), wire Agent 6/7 to produce a cited RFI, show it in the Issues page.

**Phase 4 — Memory + dashboard**
Neo4j/networkx logging (Agent 9), the live agent-flow diagram, the ROI calculator, the site map.

**Phase 5 — Predictive layer + polish**
Agent 10's heuristic pattern surfacing, QR zone tagging, visual polish pass, and a rehearsed demo script that hits every pitch claim in order.

If time runs out, stop after the phase you're in and make sure that phase's slice is bulletproof — a smaller system that works perfectly on stage beats a bigger one that might crash.

---

## 10. ACCEPTANCE CHECKLIST — MAP EVERY PITCH CLAIM TO A REAL FEATURE

Before calling this done, walk this list and confirm each is either genuinely true of the running system or clearly marked as roadmap (per the deck's own Phase 1–4 roadmap slide, which gives you honest cover for anything not yet built):

- [ ] Hands-free capture works from a real device camera/mic, no manual photo upload step
- [ ] A real object/PPE detector runs on real frames (not a canned response)
- [ ] A real depth/measurement value is computed, not a hardcoded "50mm off-spec"
- [ ] Compliance check compares that real measurement to a real stored spec value
- [ ] A hazard (e.g., missing hard hat) is genuinely detected on a real test photo
- [ ] An RFI is auto-drafted and cites a real, retrieved spec passage
- [ ] The worker actually hears a spoken response through the device speaker
- [ ] The dashboard updates live (SSE) as events happen, not on manual refresh
- [ ] Cloud/Edge toggle genuinely swaps the backing models and both paths work
- [ ] An incident is actually persisted to the graph/memory layer and visible later
- [ ] The ROI panel's headline numbers are computed, not copy-pasted from the deck
- [ ] Every "not yet implemented" item is visibly labeled as such, not silently absent

---

## 11. GUARDRAILS WHILE BUILDING

- Never hardcode a detection result, RFI text, or accuracy number "for the demo" and leave it wired that way — if you must stub something under time pressure, label it visibly (a small "SIMULATED" badge) and note it in the audit, don't disguise it.
- Keep the Gemini API key out of frontend code and out of anything committed to a public repo — load it server-side from an environment variable.
- Prefer the simplest reliable transport (chunked `fetch` POSTs) over real WebRTC unless WebRTC is already working — a flaky video pipeline on stage is the single biggest live-demo risk for this project.
- Confirm licenses before you ship: RF-DETR (Apache-2.0) and Kokoro (Apache-2.0) are commercial-clean; if you end up using Ultralytics YOLO models, note their AGPL-3.0 licensing in the README rather than ignoring it.

---

**Start with Phase 0 now.** Report the audit table, then proceed through the phases in order, checking in after each one.