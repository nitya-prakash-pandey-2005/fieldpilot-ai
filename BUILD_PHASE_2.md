# MASTER BUILD PROMPT — FieldPilot AI, Phase 2

## Preventive hazard detection, trained models, and the evidence to back both

> **How to use this file.** Paste it as your first message to a Claude Code session
> inside this repository. It is written *to* that agent, in second person. Do not
> summarise it back before starting — act on it, beginning with Section 1.
>
> **You have a GPU on a separate machine.** Sections are split into **[GPU]** and
> **[CPU]** tracks precisely so they can run in parallel: start the long training
> jobs first, then do the CPU work while they run. Never idle waiting on a
> training job.

---

## 0. YOUR ROLE AND THE STANDARD

You are the lead engineer taking FieldPilot AI from *"it logs incidents"* to
*"it prevents them"*. The system is real and working — this is not a rescue job.
Phase 1 built a genuine 10-agent pipeline; Phase 2 makes it detect the things
that actually kill construction workers, using models trained on construction
data rather than borrowed from COCO.

Three standards apply to everything you build:

1. **Nothing is claimed that is not measured.** Every accuracy number ships with
   the held-out split it came from and the date it was run. If you cannot
   measure it, say so in the UI rather than filling the gap.
2. **A refusal is a valid output.** The existing system already does this well
   (`uncalibrated`, `no_spec`, `unavailable`, `UNCERTAIN`). Preserve it. A
   fabricated hazard alert is worse than no alert, because it trains workers to
   ignore the system — and an ignored safety system is a liability, not a feature.
3. **Safety-critical code fails loud.** A crashed detector must be visible. A
   silent one that returns "no hazards" is the single most dangerous failure
   mode in this entire product.

---

## 1. WHERE THE SYSTEM ACTUALLY IS (verified — do not re-derive)

This inventory was taken from the running system. Trust it as a starting point,
but **re-verify anything you are about to change**.

### 1.1 Models currently in use — none fine-tuned on construction data

| Purpose | Model | Classes | Licence |
|---|---|---|---|
| Agent 1 detection + BoT-SORT tracking | `yolo11n.pt` (stock) | 80 COCO | **AGPL-3.0** |
| Agent 4 hard hat | `keremberke/yolov8n-hard-hat-detection` → `api/weights/best.pt` | **2**: `Hardhat`, `NO-Hardhat` | check on HF |
| Pose / fall | `yolo11n-pose.pt` | 17 keypoints | AGPL-3.0 |
| Equipment / struck-by | `forklift_yolov8n.pt` | 2: `forklift`, `person` | check |
| Edge on-device | `yolo11n-pose-int8.onnx` (3 MB) | INT8 export | AGPL-3.0 |
| Depth (default) | Metric3D `metric3d_vit_small` (torch hub) | — | BSD-2 |
| Depth (fallback) | Depth Anything V2 `metric-indoor-small-hf` | — | Apache-2.0 |
| measurecv detection | `PekingU/rtdetr_v2_r18vd` (20M) | 80 COCO | Apache-2.0 |
| measurecv segmentation | `facebook/sam2.1-hiera-tiny` (31M) | — | Apache-2.0 |
| Scale (most accurate, ±1–2 mm) | ArUco — classical OpenCV | — | BSD |
| STT | `whisper-large-v3-turbo` (Groq) → `gemini-flash-latest` fallback | — | API |
| TTS | `gemini-2.5-flash-preview-tts` / **Kokoro-82M** on-device | — | Apache-2.0 (Kokoro) |
| VLM / reasoning | `gemini-flash-latest` | — | API |
| Embeddings | `BAAI/bge-small-en-v1.5`, 384-dim | — | MIT |
| Predictive RFI | `models/weights/rfi_lgbm.txt` **DOES NOT EXIST** → scorecard heuristic | — | — |

**Critical gap:** vests, gloves, glasses and boots are **HSV colour heuristics**,
not detections (`agents/vision/ppe_detector.py`). Rebar, formwork, scaffolding,
trenches, ladders and guardrails are **not in any model's class list**.

### 1.2 Data currently loaded

- **Qdrant** (`project_default-project_drawings`): **1903 vectors**
  - 3 real OSHA PDFs (public domain) → 868 chunks
  - `data/project_documents.json` → 5 **synthetic** records, each stamped
    `(demo project record)` in its `source` so citations stay distinguishable
- `data/specs.json` — 2 tolerance entries (150 mm ±10, ACI 318-19 §7.7.1)
- Postgres: 3 zones, 5 users, `FieldIssue` rows produced by real runs
- Neo4j: `Inspection` nodes written by Agent 9
- `models/evaluation/` — real baseline + edge-benchmark JSONs

### 1.3 Architecture facts you must not break

- **Orchestrator**: `agents/orchestrator/graph.py`, LangGraph 1.2.7 `StateGraph`.
  Only ONE deferred node (`agent3_compliance`) and exactly one predecessor of
  Notification can fire per run. **`defer=True` does not chain through
  conditional edges** — a previous topology double-dispatched every alert.
  `tests/unit/test_orchestrator.py::test_no_node_fires_twice_on_fan_in` guards
  this. If you add nodes, re-run it and reason about fan-in explicitly.
- **Two loops on the worker device** (`api/routes/worker.py`): `/watch` must stay
  under ~1 s (it runs every 3 s); `/ask` may take longer because a human is
  waiting. Do not put slow reasoning in `/watch`.
- **Spec resolution refuses**: `agents/compliance/spec_registry.py` returns
  `None` rather than a default tolerance.
- **Test suites**: `pytest tests/` → 72 passing. `pytest measure/tests -c
  measure/pyproject.toml` → 294 passing. Both must stay green.

### 1.4 The licence decision you must make in Section 4

Ultralytics YOLO is **AGPL-3.0**. Fine-tuning it produces a derivative work, so
the obligation *deepens* rather than staying where it is. Decide deliberately,
record the decision in the README, and do not let it drift:

- **Option A — stay on YOLO11.** Fastest path, best tooling. Accept AGPL: either
  open-source the whole service or buy an Ultralytics Enterprise licence.
- **Option B — retrain on RF-DETR (Apache-2.0).** Follow.md's original pick,
  commercially clean, DINOv2 backbone adapts fast to new domains. Slightly more
  integration work; `measurecv` already runs RT-DETR so the family is proven here.

**Recommendation: Option B for the detector you fine-tune (T1).** You are about
to invest GPU-days into these weights; spending them on an Apache-2.0 backbone
removes a commercial blocker permanently. Keep stock YOLO11n only as the
fallback path, and note it.

---

## 2. THE ORGANISING PRINCIPLE: LEADING VS LAGGING

Everything the system detects today is a **lagging indicator** — it fires after
the event. `fall_detected` triggers on a pose aspect-ratio change, i.e. the
worker is already on the ground.

Phase 2's job is **leading indicators**: the conditions that precede an incident.

| Lagging (today) | Leading (build this) |
|---|---|
| worker fell | worker within 2 m of an **unprotected edge or floor opening** |
| no hard hat detected | worker **entered a hard-hat zone** without one |
| forklift near person | forklift **reversing** with a person in its blind arc |
| — | **trench occupied with no shoring, benching or ladder** |
| — | **ladder at unsafe angle** / not tied off |
| — | **load suspended over a walking route** |

Every hazard you add must state, in its own record, whether it is leading or
lagging. Add a `indicator_type: "leading" | "lagging"` field to the hazard schema
and surface it in the UI. Safety managers are judged on leading indicators; this
is the difference between an incident log and a prevention tool.

---

## 3. OSHA'S FATAL FOUR — YOUR COVERAGE TARGET

Roughly 60% of construction deaths. Use it to scope, and report coverage honestly.

| Hazard | Share of deaths | Current status | Phase 2 target |
|---|---|---|---|
| **Falls** | ~38% | 🟡 post-fall pose only | Edge/opening proximity, guardrail absence, ladder angle, harness/anchor |
| **Struck-by** | ~9% | 🟡 forklift proximity | Reversing vehicles, suspended loads, swing radius |
| **Caught-in/between** | ~5% | ❌ none | Trench/excavation without protection, worker between equipment and fixed object |
| **Electrocution** | ~8% | ❌ none | Overhead line proximity, exposed conductors, missing lockout/tagout |

Two of the four are entirely absent. **Prioritise falls (edge proximity) and
caught-in (trench), in that order** — highest fatality share, and both are
geometric problems solvable from a single frame plus depth, which you already have.

---

## 4. [GPU] TRACK A — MODELS AND TRAINING

**Start T1 and T2 immediately. They are the critical path.** Everything in
Sections 5–7 can be built on CPU while they run.

### 4.0 Ground rules for every training job

- **Verify every dataset before pinning it.** Licences, class lists and image
  counts change. Do not trust counts quoted from memory — including any in this
  document. Record what you actually downloaded in `docs/DATASETS.md`: name,
  URL, licence, image count, class list, download date, SHA of the archive.
- **Hold out a real test split** and never train on it. Prefer a split by *site
  or capture session*, not random image split — construction images from the same
  site are near-duplicates, and a random split inflates mAP by leaking them
  across the boundary. This is the single easiest way to produce a number that is
  wrong in your favour.
- **Log every run** to `models/evaluation/<job>_<timestamp>.json` with the config,
  dataset SHA, and metrics. The repo already uses this convention.
- **Export to ONNX + INT8 for every vision model** — the edge path is a pitch
  differentiator and an untested export is a broken promise.

### T1 — Construction detector (🔴 START FIRST, 10–16 h)

**Replaces:** stock YOLO11n's 80 COCO classes, and the HSV colour heuristics for
vest/gloves/glasses/boots.

**Datasets** (verify each; all should be construction-domain):
- **Roboflow Universe — "Construction Site Safety"** (CC BY 4.0). Classes:
  `Hardhat`, `Mask`, `NO-Hardhat`, `NO-Mask`, `NO-Safety Vest`, `Person`,
  `Safety Cone`, `Safety Vest`, `machinery`, `vehicle`. This is the backbone of
  T1 and is also named in Follow.md §7.
- **SODA** (Site Object Detection dAtaset) — construction objects, workers,
  materials, machines. Verify licence.
- **MOCS** (Moving Objects in Construction Sites) — large, machine-focused.
- **ACID** (Automated Construction Image Dataset) — heavy equipment.
- Roboflow Universe searches for the classes nothing above covers: `trench`,
  `excavation`, `guardrail`, `scaffold`, `ladder`, `rebar`, `formwork`,
  `traffic cone`, `fall protection harness`.

**Unified taxonomy** — harmonise into one class list. Suggested ~24 classes:

```
person, hardhat, no_hardhat, safety_vest, no_safety_vest, gloves, no_gloves,
safety_glasses, safety_boots, harness, mask,
excavator, forklift, dump_truck, crane, concrete_mixer, vehicle,
scaffold, ladder, guardrail, trench, rebar, formwork, safety_cone
```

Write the mapping in `models/training/taxonomy.yaml`. Different datasets use
different names for the same object (`helmet` vs `Hardhat` vs `hard-hat`);
collapsing them wrongly silently poisons the labels.

**Model:** RF-DETR (Apache-2.0) per §1.4, or `yolo11m-seg` if you accept AGPL.
**Augmentation:** heavy — construction sites are dusty, backlit, and shot into
the sun. Include motion blur, brightness/contrast jitter, and rain/dust overlays.
**Deliverable:** weights + `models/evaluation/t1_<ts>.json` with **per-class**
AP. Report the weak classes; a mean mAP hides that `no_gloves` is unusable.

### T2 — Rebar spacing keypoints (🔴 SECOND, 4–6 h)

**Replaces:** `agents/measurement/rebar_spacing.py`'s classical line detection,
which needs the frame roughly face-on. `REBAR_MODEL_PATH` is **already wired** —
set the env var and it takes the lattice path. Nothing else needs changing.

**Data:** Roboflow rebar/mesh datasets + your own captures. Label bar
intersections as keypoints.
**Model:** YOLO11n-pose retargeted to rebar intersections.
**Success criterion:** beats the ArUco+classical baseline on oblique frames, and
**does not regress the face-on case**. Compare against
`models/evaluation/measurement_synthetic_*.json`, which already exists.

### T3 — Whisper LoRA for site audio (4–8 h)

**Why:** demo rooms and real sites are loud, and the worker's accent and jargon
("rebar", "shuttering", "chajja", "lintel", "RCC") are out of distribution.
**Data:** Common Voice (accented English) + construction jargon word lists +
noise augmentation with real site audio. Mix at realistic SNR (0–15 dB).
**Integration:** add as a third backend in `agents/voice/stt.py`'s chain — the
fallback structure already exists, so this is a list entry, not a rewrite. Put it
**first** when it beats the cloud on your held-out set, otherwise last.

### T4 — VLM LoRA for deviation reasoning (12–20 h, optional)

**Honest assessment: do this last, or skip it.** `gemini-flash-latest` already
performs well on scene description and costs no GPU time. Only pursue this if
you specifically need the offline path to reason about images, which is a real
but secondary claim. Qwen2.5-VL-7B-Instruct is the pick if you do.

### T5 — Embedding fine-tune for spec retrieval (1–2 h)

**Why:** `bge-small-en-v1.5` is general-purpose. Construction spec language
("clear cover", "lap splice", "c/c spacing") retrieves poorly against it.
**Data:** build (query, passage) pairs from your own corpus + generated
questions over the OSHA chunks.
**Caution:** changing the embedding model **invalidates every stored vector**.
`EMBEDDING_DIM` is asserted in `agents/drawing/indexer.py`. You must re-index all
1903 vectors, and the collection name should change so a stale index cannot be
silently queried with incompatible embeddings.

### T6 — Predictive RFI model (< 1 h, CPU is fine)

**Why:** `models/weights/rfi_lgbm.txt` is referenced by
`agents/predictive_rfi/risk_model.py` and **does not exist**, so the system falls
back to a scorecard. Agent 10 is a frequency heuristic today (correctly labelled
as one).
**Data:** your own `FieldIssue` + `ResolvedIncident` + Neo4j inspection history.
**Honesty requirement:** with only a few dozen incidents this model will be
weak. **Report its validation AUC in the UI next to its predictions**, and keep
the heuristic labelled as a heuristic until the model genuinely beats it. Do not
replace an honest heuristic with an overfit model that looks more impressive.

### T7 — Edge export and quantisation (1 h, after T1/T2)

ONNX → INT8 for T1 and T2. **Measure the accuracy cost of INT8 and publish it** —
the repo already did this honestly for the pose model, so match that standard.
Benchmark on the actual target device before quoting NPU latency;
`/api/v1/edge/status` already carries the caveat that desktop onnxruntime ships
CPU-only.

### T8 — Depth calibration (no training, high value)

Metric3D at `assumed_fov` is ~15% accurate. **Five minutes with a printed
chessboard takes it to 1–2%** and no amount of processing substitutes for it.
Build a guided in-app calibration flow (`POST /v1/calibration/intrinsics`
already exists in measurecv). This is the **highest accuracy-per-effort item in
the entire document** and needs no GPU.

---

## 5. [CPU] TRACK B — HAZARD LOGIC AND NEW AGENTS

Build these while the GPU runs. Most need only geometry plus what you already have.

### 5.1 Agent 11 — Proximity & Zone Hazards (NEW, highest priority)

A new node in the orchestrator graph, fed by Agent 1's detections and Agent 2's
depth. **Re-read §1.3 on fan-in before wiring it.**

Rules to implement, each with `indicator_type: "leading"`:

1. **Unprotected edge / floor opening.** Detect edge or opening, project the
   worker's ground position via the depth map, alert under a threshold distance.
   Needs the `guardrail` + `trench` classes from T1; until then it must report
   `unavailable`, not guess.
2. **Exclusion zone breach.** Polygon + rule ("hard hat and vest required",
   "permit only", "no entry"). You already have zone definitions and BLE
   positioning — this is logic over existing data, buildable today.
3. **Vehicle/plant proximity.** Extend the existing forklift logic: relative
   motion, reversing detection, and a swing-radius rule for excavators.
4. **Suspended load.** Person under a crane load or hoist path.
5. **Trench occupancy.** Person inside a trench polygon with no `shoring`
   detected and no ladder within the required egress distance.

**Design constraints:** every rule states its geometric assumption and its
failure mode in the response. A proximity rule that silently assumes a flat
ground plane will fire wrongly on a slope — say so in the payload rather than
letting a false alert erode trust.

### 5.2 Agent 12 — Temporal & Behavioural (NEW)

`agents/vision/attention_tracker.py` already keeps per-`track_id` history —
build on it, do not duplicate it.

- **Dwell time**: "worker in trench > 5 min", "standing under load > 30 s"
- **Repeat offender by zone** (never by named individual — see §9 privacy)
- **PPE removal event**: had a hard hat, now doesn't — a transition, more
  informative than a static check
- **Near-miss detection**: proximity that resolved without contact. Near-misses
  are the richest leading indicator in safety practice and nothing logs them today.

### 5.3 Incident clip buffer

Keep a rolling ~10 s frame buffer per worker; on a hazard, persist the clip and
attach it to the `FieldIssue`. Turns an alert into **evidence**, which is what
settles disputes with subcontractors. Store outside the DB (filesystem or MinIO)
with a retention policy — see §9.

### 5.4 Weather and environment ingestion

One API call, high credibility, no model:
- **Wind speed** → crane/lift stop thresholds
- **Rain** → slip hazard, excavation instability
- **Heat index** → mandated rest cycles
- **Lightning** → site evacuation

Feed into zone risk. Wire as a scheduled job alongside `api/tasks/scoring.py`.

### 5.5 Toolbox-talk generator

Uses Agents 7, 9 and 10 with **zero new infrastructure**: take this week's
incidents from Neo4j, retrieve the governing clauses, and generate a 5-minute
briefing for tomorrow's crew. Every claim must cite a retrieved passage, and it
must say when there were no incidents rather than inventing a topic.

### 5.6 Close the data flywheel

`FieldIssue.is_hard_negative` **already exists and the dashboard's Reject button
already sets it** — nothing consumes it. Wire it:

1. Rejected detection → export frame + label to a review set
2. Periodic re-training set assembly
3. Track model version per detection so you can attribute regressions

This is the highest-leverage long-term feature in the document: it is the only
mechanism by which the system improves after you stop working on it.

---

## 6. [CPU] TRACK C — PRODUCT AND OPERATIONS

- **Escalation ladder with acknowledgement.** A CRITICAL alert nobody
  acknowledged must escalate. Track ack state; an unacknowledged safety alert is
  itself an incident.
- **Shift handover report.** Auto-generated: open hazards, unresolved RFIs, zones
  at risk.
- **Subcontractor scorecard.** Aggregate by company, never by named worker (§9).
- **Permit-to-work + LOTO register.** Digital permits gate exclusion zones —
  ties directly into 5.1.2.
- **Regulatory export.** OSHA 300-log-shaped export of recordable incidents.
- **Offline store-and-forward hardening.** `scripts/offline_queue.py` exists;
  prove it end-to-end on the phone with the network genuinely off, and show the
  sync in the UI.

---

## 7. EVALUATION — THE PART THAT MAKES THE REST CREDIBLE

**Build this before you finish T1, not after.** Without it you cannot tell
whether a fine-tune helped.

1. **Held-out test set**, split by site/session (§4.0), never trained on.
2. **`scripts/evaluate_models.py`** producing, per class: precision, recall, AP,
   and the confusion matrix. Save to `models/evaluation/`.
3. **Baseline comparison** — stock YOLO11n vs T1 on the same set. The delta is
   your real headline number and it belongs in the README and the pitch.
4. **Safety-weighted metrics.** Accuracy is the wrong headline for safety.
   A missed `no_hardhat` (false negative) is far more costly than a false alarm.
   Report **recall on the NO-* classes specifically**, and tune thresholds for
   recall over precision on those classes. State the operating point you chose.
5. **Latency budget** per agent on both cloud and edge, measured not estimated.
6. **Surface the numbers in the UI.** The Agent Flow page already shows the
   backend that served each node; add the model version and its held-out score.

---

## 8. INTEGRATION CONTRACTS — HOW TO PLUG NEW MODELS IN

Follow these or you will break working code:

- **Detector swap**: keep `VisionPipeline.analyze_ndarray()`'s output schema.
  Downstream (`agent1_vision`, `agent4_hazard`, the worker `/watch` loop) reads
  `assets_detected[].asset_type`, `compliance_checks[].ppe_score`, `fall_events`,
  `struck_by_events`. Add fields; do not rename.
- **New hazard types**: extend the hazard dict with `type`, `indicator_type`,
  `confidence`, `rule`, `assumption`. The worker `/watch` endpoint fingerprints
  hazards by `type` for debouncing — a new type is automatically debounced, but a
  type that changes every frame will alert every 3 s. Make types stable.
- **New agents**: add to `AGENTS` and `EDGES` in `agents/orchestrator/graph.py`.
  The Agent Flow UI renders from `GET /api/v1/orchestrator/graph`, so the diagram
  updates itself. **Then run the fan-in test.**
- **New models**: register in `/api/v1/worker/status` and
  `/api/v1/orchestrator/status` so the UI reports availability rather than
  assuming it. Report *configured* vs *verified* separately — a present API key
  is not a working one.

---

## 9. GUARDRAILS — NON-NEGOTIABLE

**Honesty**
- Never hardcode a detection, accuracy figure or RFI. If you must stub, label it
  visibly (the repo already uses a `SIMULATED` badge and a `SEEDED` badge) and
  note it in the audit.
- Keep the `demo project record` provenance suffix on synthetic corpus entries.
- A model that did not load must report why. Never let "unavailable" render the
  same as "nothing detected" — for a safety system these are opposites.

**Privacy — read before building Section 5.2 or 6**
- **Do not build face recognition or biometric identification.** Consent and
  data-protection exposure is severe and it adds nothing to hazard detection.
- Aggregate by **zone, crew or subcontractor** — never publish per-named-worker
  safety scorecards. That turns a safety tool into a disciplinary one, and workers
  respond by avoiding it.
- Video clips (5.3) are personal data. Set a retention period, document it, and
  delete on schedule.
- If you deploy in the EU/UK, an automated system monitoring workers needs a DPIA.
  Note this in the README rather than discovering it later.

**Licensing**
- Record the §1.4 decision in the README with its consequence spelled out.
- Every dataset's licence goes in `docs/DATASETS.md`. CC BY 4.0 requires
  attribution — actually attribute it.
- Do not ship a model whose training data licence you cannot name.

**Safety engineering**
- This system **advises**; it does not replace a competent person. Say so in the
  UI. Do not let a PASS verdict read as sign-off.
- Tune NO-* classes for recall (§7.4) and state the operating point.
- Never auto-close a safety alert. A human acknowledges it.

---

## 10. SUGGESTED ORDER

**Immediately, in parallel:**
- [GPU] Launch **T1**. It blocks the most.
- [CPU] Build the **evaluation harness** (§7) — you need it to judge T1.
- [CPU] Build **T8 depth calibration** — best accuracy-per-effort in the document.

**While T1 runs:**
- [CPU] **Agent 11** exclusion zones + vehicle proximity (no new classes needed)
- [CPU] **Incident clip buffer** (§5.3)
- [CPU] **Data flywheel** wiring (§5.6)

**When T1 lands:**
- [GPU] **T2**, then **T7** export
- [CPU] Agent 11's edge/trench rules, now that the classes exist
- [CPU] Re-run evaluation, publish the baseline delta

**Then:** T3, T5, T6, weather, toolbox talks, ops features.

**Stop and harden when you run out of time.** A smaller system that works
perfectly and reports its own limits beats a larger one that might crash — and
in a safety product, a confident wrong answer is worse than no product at all.

---

## 11. ACCEPTANCE CHECKLIST

Confirm each is genuinely true of the running system, or visibly marked roadmap.

**Models & data**
- [ ] A detector fine-tuned on construction data is running in Agent 1
- [ ] Per-class AP published against a held-out split, split by site not randomly
- [ ] Baseline delta vs stock YOLO11n published
- [ ] Vests/gloves/glasses are model detections, or still honestly labelled heuristics
- [ ] `docs/DATASETS.md` lists every dataset with licence and download date
- [ ] Licence decision (§1.4) recorded in the README
- [ ] INT8 export exists and its accuracy cost is published

**Hazards**
- [ ] At least one genuine **leading** indicator fires on a real frame
- [ ] Trench OR unprotected-edge detection works, or reports `unavailable` honestly
- [ ] Exclusion-zone breach detection works end to end
- [ ] Near-miss events are logged distinctly from incidents
- [ ] Every hazard record carries `indicator_type`
- [ ] Fatal Four coverage stated honestly in the README

**System**
- [ ] `pytest tests/` and `pytest measure/tests -c measure/pyproject.toml` green
- [ ] Fan-in test still passes after adding agents
- [ ] Agent Flow diagram shows the new agents automatically
- [ ] `/watch` still returns in under ~1 s
- [ ] Model version + held-out score visible in the UI
- [ ] Clip retention policy documented
- [ ] No per-named-worker scorecard exists anywhere

---

**Start with Section 1's verification, launch T1, then work Sections 5 and 7
while it trains. Report the audit before you begin building.**
