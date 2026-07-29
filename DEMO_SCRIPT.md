# FieldPilot AI — Round 2 Demo Video Script

Stage 2 is judged by this recorded video, not live — so treat this as the actual submission, not a rehearsal for something else. Everything below only lists things that were verified working against the real running stack this session (`docker compose up`, real Postgres/Neo4j/Qdrant/Groq/Gemini) — nothing here is aspirational.

## 0. Before recording

- `docker compose up -d` — confirm all 4 containers healthy.
- `python api/main.py` (or `uvicorn main:app`) from `api/` — confirm `GET /api/v1/health/agents` returns all 10 agents `"operational"`.
- `cd frontend/engineer-dashboard && npm run dev` — dashboard on `localhost:3000`.
- Have a **real hardhat and hi-vis vest** on hand (or a willing teammate wearing one) — the PPE detector is real, so real PPE gets real PASS/FAIL results, not staged ones.
- Optional: a toy/model forklift or any small vehicle-like object, to trigger the new struck-by detector.

## 1. Cold open (15s)

Say what this is and what's being shown live vs. what's simulated:
> "This is FieldPilot AI, running against a real backend — Postgres, Neo4j, Qdrant, and live LLM calls. The Meta glasses haven't shipped yet, so Tier 1 runs on a laptop webcam today, exactly as our execution plan called for — audio-only, no display, matching the Wayfarer Gen 2's real hardware constraints."

## 2. Live hazard detection (60-90s) — webcam, not the stock sample video

Run: `python scripts/live_camera_pipeline.py --source laptop --zone A12`

Shot list, each one a real, reproducible trigger:
1. **PPE compliant** — stand in frame wearing the real hardhat/vest. Show the dashboard's Zone A12 pin turn green / low risk.
2. **PPE violation** — remove the hardhat. Point out: real HSV+model-based PPE detector (not scripted), real hazard score jump, real earcon (single medium beep) plays before the spoken alert, dashboard's Active Issues panel gets a new real card with the confidence bar.
3. **Fall** — stage a controlled fall/crouch-to-floor movement. Point out: distinct 3-beep urgent earcon, different from the PPE beep, "STOP WORK" language in the spoken alert.
4. **Struck-by (new this session)** — hold up the toy vehicle near yourself in frame. Point out: this is a *second* real fine-tuned model (`keremberke/yolov8n-forklift-detection`) added specifically for OSHA's "struck-by" Focus Four category, distinct alternating-tone earcon.
5. **Attention escalation** — trigger a PPE violation and stand still for 4+ seconds without looking at the camera/hazard. Point out the dwell-time state machine moving PASSIVE → ESCALATED, and the escalation-specific earcon/message.

## 3. Compliance + measurement (30s)

`POST /api/v1/compliance/validate` with a real deviation (already demonstrated safe via `scripts/load_test.py` — cite the real number: **median 271ms hazard-to-alert latency**, under the 500ms target).
> "Every FAIL writes to a real Postgres FieldIssue, a real Neo4j Inspection node, and dispatches a real notification — not a mocked response."

## 4. Spec Q&A / RAG (30s)

On `/memory` page, ask: *"What are the requirements for scaffold guardrails?"*
- Show the real cited answer pulling from the newly-ingested OSHA Scaffold Use and Construction Industry Digest PDFs (real public OSHA publications, not fabricated text) — point out the citation with document name.

## 5. Predictive RFI (20s)

`/rfis` page — show a real prediction with `basis` grounded in actually-retrieved historical incidents (not a hardcoded blob), citing real incident IDs from the Qdrant `learning_incidents` collection.

## 6. Cross-worker broadcast (20s, needs 2 devices/tabs)

Open `/zones` for Zone A12 in one tab, Zone B3 in another. Trigger a HIGH/CRITICAL hazard in A12 — show the advisory reaching the A12-zone WebSocket listener and **not** reaching B3's.

## 7. Executive dashboard / learning loop (20s)

`/` home page KPI bar and `/executive` — point out the `LIVE` vs `DEMO` badges are real, not decorative: numbers pulled from `GET /learning/stats` and `GET /learning/trends` once real incidents exist.

## 8. Close (15s)

State the two real, measured numbers on screen:
- **271ms** median hazard-to-alert latency (target: <500ms) — `scripts/load_test.py` / direct measurement, this session.
- **100%** pass rate across all 4 baseline validation checks (PPE, fall, ONNX parity, attention state machine) — `models/evaluation/baseline_20260729_075351.json`.
- **0 dropped events** across 275 requests under 5 concurrent simulated workers (target: 3+).

Then the honest-numbers framing from the Master Plan:
> "Every number we just showed you is something we actually measured this week, including where it isn't perfect — compliance validation runs ~270ms median because it's doing a real synchronous database write and notification dispatch, not because we hid the cost."

## What NOT to claim

- Do not claim real Meta glasses hardware — say "webcam standing in for Tier 1, glasses integration pending hardware."
- Do not claim the fine-tuning/flywheel loop retrains a model live (`scripts/nightly_flywheel_training.py` is an intentionally labeled simulated stub) — the real, verifiable part is the feedback data collection (`POST /issues/{id}/reject`) and the dataset export (`GET /export-dataset`), both real.
- `data/sample_construction.mp4` is NOT construction footage (it's a generic indoor people-detection clip) — don't use it on camera; record real webcam footage per Section 2 instead.
