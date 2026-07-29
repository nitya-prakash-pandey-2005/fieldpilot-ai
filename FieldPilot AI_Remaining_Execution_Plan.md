# FieldPilot AI — Remaining Execution Plan

_Companion to `FieldPilot AI_Master_Executation_Plan.md` (the 15-day phased build) and `system_prompt.md` (the full production architecture). This doc is the honest gap list between where the repo actually is today and "both documents fully implemented at production level" — written from a real audit of the code, not from the plan documents' aspirations._

## 0. How to read this

Every item below is tagged:
- ✅ **Done** — real, verified working (this session or earlier)
- 🟡 **Partial** — real code exists but a critical piece is stubbed/disconnected/hardcoded
- ❌ **Missing** — does not exist at all, greenfield build

Read the **Reality check** section (§4) before committing to a timeline. Some of this — a self-hosted multi-GPU vLLM cluster, Kubernetes, full RBAC, BIM/IFC — is enterprise-SaaS-scale work, not a continuation of a hackathon sprint. This doc lays out everything so you can choose deliberately, not because all of it should be built next.

---

## 1. Master Execution Plan — Phase 0 status (Days 1-5)

**✅ Done and verified this session** (see git history / prior session): real fall & PPE detection tests, ONNX export + quantization, attention dwell-time state machine wired into the live pipeline, unified Postgres DB (compliance FAIL → FieldIssue → notification dispatch verified live), unified RAG (real cited Q&A against the OSHA PDF), real Slack/Twilio send paths, offline store-and-forward queue (verified live), Gemini TTS (verified real audio output), frontend zone map / attention indicator / compliance card.

One correction to a stale finding: an earlier automated audit flagged "two never-synced Postgres databases" as a live issue — that was already fixed this session (DB unification, `infra/docker-compose.yml` removed, `agents/compliance/validator.py`/`agents/notification/router.py` rewritten off raw asyncpg). The `askthewall` references remaining in those files are historical comments only, not live code paths.

**Day 5 item not yet done**: the plan's "full mock end-to-end rehearsal... 10 minutes without crashing, 3+ hazard types trigger through to a spoken alert" — this is a live rehearsal/demo run, not a code task. Do this once Gemini TTS + the live camera pipeline are run together end-to-end.

---

## 2. Master Execution Plan — Phase 1 (Days 6-10): real glasses integration

**Status: ❌ blocked on hardware.** Everything here needs the physical Ray-Ban Meta Wayfarer Gen 2. Nothing to build in advance except making sure the webcam-based Tier 1 pipeline (already done) has zero code paths that assume a display exists (audio/haptic only) — worth a quick explicit check once glasses arrive, not before.

| Day | Item | Depends on |
|---|---|---|
| 6 | Swap Mock Device Kit for real glasses stream; confirm 12MP/3K/30fps | Physical glasses |
| 7 | Continuous Tier 0/1 on-device; shoot real labeled dataset; earcon system (per-hazard audio cues before TTS) | Physical glasses |
| 8 | Real measurement/scale calibration via live feed + physical reference object; gate Tier 2 (cloud reasoning) to fire only on Tier 1 flag or explicit voice query; severity-scaled phone haptic | Physical glasses + a real reference object |
| 9 | Wire deviation detection → auto RFI draft into the real live pipeline; re-fine-tune edge model on real glasses footage, compare against Day-3 baseline | Physical glasses + Day 7 footage |
| 10 | Full live end-to-end test with spoken+earcon+haptic alerts; record real battery drain over 1 continuous hour | Physical glasses |

**What CAN be prepped now, without glasses:**
- The earcon system (Day 7) is pure audio-asset work — distinct short sound patterns per hazard category (fall / no-hardhat / no-vest / escalated-attention / etc.) can be designed, generated, and wired into the TTS/alert pipeline (`agents/voice/tts.py`, `scripts/live_camera_pipeline.py`'s `VoiceAlerter`) today, tested on the webcam pipeline, then simply pointed at the glasses' speaker once hardware arrives.
- The Tier 2 gating logic ("cloud reasoning only fires on a Tier 1 flag or explicit voice query") is pure backend logic, buildable and testable against the webcam pipeline now.
- Severity-scaled haptic patterns (Day 8) need a phone, not glasses — can be prototyped against any Android/iOS device now if one's available.

---

## 3. Master Execution Plan — Phase 2 (Days 11-15): learning loop, broadcast, hardening

| Day | Item | Status | Note |
|---|---|---|---|
| 11 | Feedback-loop logging (engineer approve/reject → labeled training example) | 🟡 Partial | `agents/learning/ingestor.py` writes real Postgres + Neo4j rows on issue resolution; **no hard-negative flagging logic exists** — `FieldIssue.is_hard_negative` column exists but nothing sets it from a reject action. `ActiveIssuesPanel.tsx`'s reject button already calls `/issues/{id}/reject` — verify that route actually sets `is_hard_negative=1` (needs checking/wiring). |
| 11 | Learning-loop metric panel on dashboard | 🟡 Partial | `GET /learning/stats` and `/learning/trends` are real (live Postgres aggregates) but `ExecutiveCharts.tsx` never calls `/trends` — hardcoded `DEMO_RISK_DATA`/`DEMO_INCIDENT_DATA` instead. Wiring exists on the backend; the frontend call was never made. |
| 11 | Cross-worker hazard broadcast (same zone gets advisory, different zone doesn't) | ❌ Missing | No multi-device/zone-scoped broadcast logic anywhere. `broadcast_event()` in `api/main.py` exists but has zero callers (dead code) and broadcasts to a single `project_id` channel, not zone-scoped. Needs: zone-tagged WebSocket rooms, a second test device/session to receive the advisory. |
| 12 | Real fine-tuning cycle on feedback so far, compare vs Day-3 baseline | ❌ Missing (by design, currently) | `scripts/nightly_flywheel_training.py` is an intentional simulated stub (fake loss numbers, commented-out `torch`/`peft`/`transformers` imports). Also, `agents/learning/ingestor.py::_write_qdrant` is **hardcoded to always fail** (`raise ConnectionRefusedError` unconditionally) — the vector-memory leg of the flywheel never writes anything regardless of environment. Turning this into a real LoRA fine-tune is a genuine ML-infra project (GPU access, a real training script, dataset assembly from `GET /export-dataset` which IS real). |
| 12 | Re-test offline store-and-forward in real deployment env | 🟡 Partial | The mechanism is real and verified (this session, on webcam pipeline). "Real deployment environment" = once glasses/phone hardware exists. |
| 13 | Load-test backend under simulated multi-worker load | ❌ Missing | No load test exists. Straightforward to build (e.g. `locust` or a simple concurrent-client script hammering `/live/frame` and `/compliance/validate`) once desired. |
| 13 | Confidence indicator on dashboard (model's own certainty, not binary) | 🟡 Partial | `ComplianceEngine` already computes and returns a `confidence` value (from measurement confidence); `PredictedRFIPanel.tsx` already shows a confidence ring for RFI predictions. Not yet added to the hazard/compliance cards on the main issues panel — `ComplianceCard.tsx` doesn't currently surface `confidence` even though the backend has it. |
| 13 | Polish dashboard, remove all placeholder/mock data | 🟡 Partial | See §5 below — Executive Dashboard is ~80% mock still. |
| 14-15 | Rehearsals + pitch deck + backup video | ❌ Not applicable yet | Logistics/presentation work, not code. |

---

## 4. system_prompt.md — full production architecture gaps

These are NOT in the Master Execution Plan's 15-day scope at all — they're system_prompt.md's "production blueprint" ambitions. Audited fresh this session.

### 4.1 Auth / RBAC — ❌ Missing entirely
No JWT, no login flow, no RBAC, no MFA anywhere in API or frontend (verified via full-repo grep). `system_prompt.md` §9 wants 5 roles (Worker/Engineer/PM/Admin/Executive) with MFA for Engineer+. This is a from-scratch build:
- Backend: JWT issuance/refresh (`/auth/login`, `/auth/refresh`, `/auth/logout` — none exist), a `Depends(get_current_user)` pattern applied to every route, a `User`/`Role` SQLAlchemy model.
- Frontend: login page, token storage, route guarding, role-based UI hiding.
- This is a prerequisite for literally any real multi-user deployment — worth prioritizing above most of §4.2-4.9 if "production" is the actual goal, since without it anyone can call `POST /graph/query` (raw Cypher passthrough, no auth at all — also a real security hole worth flagging on its own).

### 4.2 Knowledge Graph Agent (Agent 4) — 🟡 Partial, functionally hollow
Real Cypher queries exist (`agents/knowledge_graph/queries.py` implements all 4 queries system_prompt.md specifies), but **nothing in the codebase ever creates the relationships those queries depend on** (`LOCATED_IN`, `INSPECTS`, `BELONGS_TO`, `SUPERSEDES`, or `Inspection` nodes at all). `scripts/seed_demo_data.py` only creates `Zone`/`Asset`/`Drawing`/`RFI` nodes plus one `RFI-[:ABOUT]->Asset` edge. Result: 3 of 4 specified queries always return empty against a real, running, seeded Neo4j.
**To fix**: wire real write-paths — when an `Inspection` happens (there isn't one today — QC inspection isn't modeled anywhere), when an `Asset` is detected in a `Zone` (vision pipeline already knows zone_id and asset type per frame — needs a write to Neo4j, not just Postgres), when a `Drawing` supersedes another (version_control scanner already extracts this, needs to write the edge instead of just comparing).

### 4.3 Predictive RFI Agent (Agent 6) — 🟡 Partial, defaults to a static mock
- `asset_type` is hardcoded to `"rebar"` regardless of actual work type (`# Assuming rebar for MVP` — never finished).
- Zero Qdrant similarity search despite being specified — historical matching is one hardcoded-asset Cypher query.
- LLM synthesis defaults to `LLM_BACKEND=mock`, returning the exact same JSON blob (`prediction_id: "pred-mock-1234"`) every single call regardless of input, and falls back to that same mock on any parse failure even with a real LLM configured.
**To fix**: parse `work_type` into a real asset-type mapping; add a Qdrant collection of historical RFI descriptions + embed-and-search; set `LLM_BACKEND=groq` (already used elsewhere in this codebase) or wire the Gemini key already added this session.

### 4.4 Version Control Agent (Agent 8) — 🟡 Partial, OCR deliberately disabled
Regex/decision logic is real and solid. But `HAS_PADDLE = False # Forced to false to bypass slow startup` — PaddleOCR is unconditionally disabled, so `MockPaddleOCR.ocr()` returns the same hardcoded string (`"DWG NO: S-101 REV: R3 DATE: 2024-08-10"`) no matter what image is actually passed in. The `/commit` endpoint is a pure hardcoded stub (fixed commit hash, fixed 2-entry history) despite its docstring claiming a real Neo4j write.
**To fix**: re-enable PaddleOCR (the "slow startup" tradeoff needs revisiting — maybe lazy-load on first real request instead of at process start), wire `/commit` to an actual Neo4j `MERGE`/version-edge write.

### 4.5 Learning Agent (Agent 10) — 🟡 Partial, one leg permanently broken
Postgres ingestion, Neo4j writes (with real Redis retry-queue fallback), and `GET /export-dataset`/`GET /stats`/`GET /trends` are all genuinely real, computed from live data. But `_write_qdrant` is **hardcoded to always raise** `ConnectionRefusedError` — not a real attempt that happens to fail, an intentional permanent stub (`# We simulate a Qdrant failure since Qdrant isn't natively running on windows`). Since Qdrant now runs fine in the unified `docker-compose.yml` (verified this session for RAG), this stub is now simply wrong and should be replaced with a real write.
**To fix**: replace the hardcoded raise with a real `qdrant_client.upsert()` call embedding the incident description (reuse the same `BAAI/bge-small-en-v1.5` model now standardized across the RAG paths, per this session's WP-E).

### 4.6 Mobile app (React Native worker app) — 🟡 Partial, exists but unaudited
`frontend/mobile/` is a real Expo/React Native project with 6 screens (Scan, Issues, History, Ask AI, Voice, Profile) and real navigation. Confirmed `ScanScreen.tsx` makes a real API call. **Not yet screen-by-screen audited** for how much of each screen is wired vs mock — that's the next step, not a rebuild.
**To fix**: audit each of the 6 screens the same way this session audited the web dashboard's components (real API calls vs local mock arrays), then close whatever gaps are found.

### 4.7 Executive Dashboard — 🟡 Partial, ~80% still mock
Only 2 of ~10 displayed numbers (`resolveTime`, `workersAssisted` on the KPI bar) are live, pulled from the real `GET /learning/stats` endpoint. Everything else is hardcoded: `riskIndex`/`accuracy` on the KPI bar, all of `ExecutiveCharts.tsx` (comment literally says the real endpoint exists and was never called), and all of `ROICalculator.tsx` (client-side fake math with a hardcoded "12:1 ROI" claim).
**To fix**: this is the highest-value-per-hour item in this whole doc — the backend endpoints mostly already exist (`/learning/trends`), it's purely frontend wiring:
1. `ExecutiveCharts.tsx` → call `/api/v1/learning/trends`, replace `DEMO_RISK_DATA`/`DEMO_INCIDENT_DATA`.
2. `ExecutiveKPIBar.tsx` → figure out real sources for `riskIndex` (zone risk aggregation already exists in `HazardAnalyzer.aggregate_zone_risk` / Neo4j `get_zone_risk_score`) and `accuracy` (this session's `models/evaluation/*.json` baselines, or a new endpoint that surfaces the latest one).
3. `ROICalculator.tsx` → base its math on real `GET /learning/stats` cost-avoided figures instead of a fully hardcoded formula.

### 4.8 Digital Twin (BIM/IFC) — ❌ Missing beyond a dead WebSocket
`/ws/twin/{project_id}` accepts connections and has a `broadcast_event()` helper — but **nothing in the entire codebase calls `broadcast_event()`** (dead code; even `agents/compliance/validator.py`'s comment about "broadcast the event to the live dashboard twin" refers to the separate `broadcast_event` in `main.py` used for compliance events, a different mechanism, not this one). No `ifcopenshell`/IFC parsing exists anywhere despite being specified with sample code in system_prompt.md §7.2.
**To fix**: this needs the same write-side work as §4.2 (Knowledge Graph) — the twin is supposed to be driven by the same Asset/Zone state changes; there's no point building IFC parsing before there's a real graph for it to update. Sequence this after §4.2.

### 4.9 Infra: Monitoring, CI/CD, Kubernetes/Terraform, vLLM/Qwen3, MinIO — ❌ All missing, all greenfield
- **Monitoring** (Prometheus/Grafana/Loki): zero config anywhere.
- **CI/CD**: no `.github/workflows/`, no pipeline of any kind.
- **Kubernetes/Terraform**: `infra/k8s/` and `infra/terraform/` are empty directories (0 files).
- **Self-hosted LLM serving** (vLLM/Qwen3-32B on 4x GPU): not attempted, and per this session's earlier decision, deliberately deferred in favor of Groq cloud — revisit only if there's a real GPU budget; this is a genuinely large infra undertaking, not a code change.
- **MinIO** (S3-compatible file storage): not provisioned; photos/drawings currently just live on local disk (`api/routes/drawing_intelligence.py`'s `temp_dir`) with no object storage or retention policy.

None of these block making the actual product work better — they're deployment/ops maturity, relevant once there's a real multi-user, multi-site deployment to run. Building Kubernetes manifests for a system with no auth and a hollow knowledge graph would be solving the wrong problem first.

---

## 5. Known data-consistency issue (worth a line item)

`scripts/seed_demo_data.py` seeds Neo4j with zone IDs `"A12"/"B3"/"C7"` while `api/main.py`'s Postgres seeding uses `"z-1"/"z-2"/"z-3"` (with `zone_code` "A12" etc. as a separate field — the correct pattern, see `FieldIssue.zone_code`). Any code that tries to join graph data and relational data by treating these as the same ID will silently break. Worth a quick audit of `scripts/seed_demo_data.py` to align it with the `zone_code`-vs-`id` convention already established in `api/models/zones.py`.

---

## 6. Recommended sequencing

Given glasses arrive soon and Phase 1/2's glasses-dependent items simply can't start early, here's a priority order for what CAN be worked on now, roughly by (impact × how much real code already exists to build on):

1. **Executive Dashboard real wiring** (§4.7) — highest value-per-hour, backend mostly already there, purely frontend work.
2. **Auth/RBAC** (§4.1) — foundational; every other "production" claim is undermined without it, and the unauthenticated raw-Cypher `/graph/query` endpoint is a real hole worth closing regardless of broader auth scope.
3. **Learning Agent Qdrant fix + hard-negative flagging** (§4.5, part of Phase 2 Day 11) — the stub is a one-function fix now that Qdrant actually runs; hard-negative flagging is small and unblocks real feedback-loop data collection starting immediately, so the longer this waits the less training data accumulates.
4. **Knowledge Graph write-paths** (§4.2) — unlocks §4.2, §4.3's real similarity search groundwork, and §4.8 (twin) all at once; do this before touching Version Control's `/commit` stub or the Digital Twin, since they both depend on a real graph existing.
5. **Predictive RFI real similarity search + LLM backend fix** (§4.3) — depends on §4.2's Qdrant/graph groundwork being in place.
6. **Version Control real OCR + real `/commit`** (§4.4) — re-enable PaddleOCR, wire graph writes (needs §4.2 first).
7. **Mobile app screen-by-screen audit** (§4.6) — parallelizable with anything above; independent surface area.
8. **Digital Twin BIM/IFC** (§4.8) — do last among the agent work; needs §4.2's real graph to be meaningful.
9. **Cross-worker broadcast, load testing, confidence indicators** (Phase 2 Day 11/13 leftovers) — small, can slot in anywhere.
10. **Monitoring/CI/CD/Kubernetes/Terraform/vLLM/MinIO** (§4.9) — do this last, and only once there's a real deployment target and multi-user auth to actually operate; building ops infrastructure for a single-tenant, unauthenticated hackathon app is premature.

Glasses-dependent Phase 1/2 items (§2, §3) run in parallel with whichever of the above you pick, the moment hardware arrives — they don't compete for the same engineering time except where noted (e.g. earcon design, Tier 2 gating logic can be done now).

---

## 7. Reality check

Read literally, "completely implement both files fully functional at production level" means: multi-tenant auth with MFA, a populated multi-relationship knowledge graph, real vector-similarity RFI prediction, working OCR-based drawing version control, a real LoRA fine-tuning loop, full BIM/IFC digital twin, a monitoring stack, CI/CD, Kubernetes deployment, and (if taken literally) a self-hosted 4-GPU LLM cluster — on top of finishing the glasses-dependent hardware phases that haven't started. That is genuinely multiple engineer-months of work for a small team, not a continuation of one coding session.

This doc exists so you can pick real, sequenced priorities rather than everything appearing as one undifferentiated wall of remaining work. Tell me which numbered section to start on and I'll work it the same way as the Phase 0 close-out — one verified, tested piece at a time, checking in as I go.
