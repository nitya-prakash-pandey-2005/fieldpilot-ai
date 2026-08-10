# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend (run from api/ — main.py appends both repo root and api/ to sys.path)
cd api && python -m uvicorn main:app --reload            # http://localhost:8000
python -m uvicorn main:app --host 0.0.0.0 --port 8000    # needed for phone/LAN worker view

# Tests
python -m pytest tests/                                   # FieldPilot unit + integration
python -m pytest measure/tests -c measure/pyproject.toml  # measurecv engine (own config)
python -m pytest tests/unit/test_orchestrator.py::test_no_node_fires_twice_on_fan_in

# End-to-end check against a running backend — PASS / DEGRADED / FAIL per agent
python scripts/verify_system.py [--base-url http://host:8000]

# Frontends
cd frontend/engineer-dashboard  && npm run dev   # :3000  (npm run lint = eslint)
cd frontend/executive-dashboard && npm run dev   # :3001
cd frontend/mobile && npx expo start             # Expo Go SDK 54

# Infra (all optional — see degradation below)
docker compose up -d          # postgres, qdrant, redis, neo4j, mediamtx
python scripts/ingest_spec.py # index the spec corpus (API must be running)
python scripts/serve_worker_https.py  # HTTPS dev server so a phone can grant camera/mic
pip install -e "./measure[models,api]" timm mmengine   # depth/dimensioning backend
```

There is no root `pyproject.toml`/`pytest.ini`; deps live in `api/requirements.txt`,
per-agent `requirements.txt` files, and `measure/pyproject.toml`.

Python 3.11+, Node 20+. Demo logins (seeded on first boot):
`{worker,engineer,pm,admin,executive}@fieldpilot.demo` / `fieldpilot123`.

## The docs, and which one is authoritative

- **`system_prompt.md`** (1500 lines) — the full product/architecture spec: per-agent
  I/O contracts, API reference, target metrics (§13.1's <5s end-to-end budget is cited in
  code). Consult it for intended behaviour of an agent before redesigning one.
- **`Follow.md`** — the Stage-3 build prompt: hardware-substitution spec and guardrails.
  README documents where the build deliberately diverged from it and why.
- **`TESTING_GUIDE.md`** — the manual end-to-end verification walkthrough (curl per
  feature, expected responses). The scripted equivalent is `scripts/verify_system.py`.
- **`docs/MEASUREMENT_INTEGRATION.md`** — the two-engine measurement split and accuracy
  bounds. `docs/TRAINING_PLAN.md`, `measure/docs/accuracy.md` for the model side.
- `DEMO_SCRIPT.md` / `DEMO_CHECKLIST.md` / `DEVPOST_SUBMISSION.md` — presentation only.

**Two conflicting agent numberings exist.** `system_prompt.md` and the `agents/` directory
layout use the *spec* numbering (3 = Drawing Intelligence, 4 = Knowledge Graph,
5 = Compliance, 7 = Memory, 9 = Notification). README and `agents/orchestrator/graph.py`
node names use the *runtime* numbering (3 = Compliance, 4 = Hazard, 5 = Voice, 6 = RFI,
7 = Knowledge, 8 = Notification, 9 = Memory). Always resolve "Agent N" against the
directory or graph node, never the number alone.

## Architecture

Three tiers: FastAPI backend (`api/`) → agent modules (`agents/`) → Next.js dashboards
(`frontend/`). Config is entirely env-driven; `.env.example` is the documented contract.

**The orchestrator is the spine.** `agents/orchestrator/graph.py` wires the ten agents
into a LangGraph `StateGraph` (voice → vision → {measurement ‖ hazard} → compliance →
conditional knowledge/RFI → notification → memory → learning). Read its module docstring
before touching it: the topology is load-bearing. Compliance is `defer=True` to join the
parallel lanes exactly once, and Voice is deliberately *sequential* rather than a parallel
lane because a deferred multi-predecessor Notification double-fired alerts.
`GET /api/v1/orchestrator/graph` is generated from the same structures the graph compiles
from, so the UI diagram cannot drift from execution.

**Agent modules are the implementations; routes and graph nodes are thin.** Each
`agents/<name>/` package owns its logic; `api/routes/*.py` (one file per capability) and
the graph nodes only sequence and trace. Put behaviour in the agent module.

**Everything degrades rather than fails, and says so.** Postgres → SQLite at
`api/fieldpilot.db`; Qdrant → embedded mode in `data/qdrant_local` (exclusive dir lock —
one process only, which is why ingestion goes over HTTP); Neo4j has deliberately short
timeouts (`api/db.py`) so a dead graph DB can't blow the <5s alert budget. Preserve this
pattern: a missing dependency reports its state, it does not silently substitute.

**Never fabricate data to fill a gap.** This is the repo's strongest convention and most
comments exist to enforce it: no spec match → `no_spec` and no verdict; no retrieved
passage → RFI marked `uncited`; no depth weights → `status: "unavailable"`; edge mode
never falls back to a cloud call; demo issues are not seeded because a detection only
exists once something detected it. Simulated values carry a SIMULATED label in the UI and
synthetic corpus entries carry a `(demo project record)` provenance suffix.

**Real-time paths:** in-memory `EventBus` in `api/pubsub.py` fans out to SSE
(`routes/stream.py`, `live_feed.py`); agent trace events publish through it live.

**Cloud vs edge is a real model swap**, not a flag: PyTorch YOLO11n + Metric3D + Gemini TTS
vs INT8 ONNX pose + no depth + on-device Kokoro (`agents/edge/runtime.py`).

**Scene reasoning has two backends**, selected by `VLM_BACKEND` (`agents/vision/vlm_analyzer.py`):
`gemini` (cloud API, default) and `gemma` (local Gemma 4, `agents/vision/gemma_analyzer.py`).
They never fall back to each other — same rule as edge mode. Gemma additionally offers
`identify_objects()`, open-vocabulary naming for assets YOLO has no class for (rebar cage,
formwork, cable tray); YOLO still owns the boxes, because Gemma's coordinates are unverified
and must not reach metrology. Two runtimes: `GEMMA_RUNTIME=transformers` needs
transformers>=5.0 and a ≥16GB GPU (the model is one 16GB shard); `llama_cpp` talks to
`scripts/serve_gemma_gguf.py` and is the path that fits a 6GB card.

**Trained weights drop in via env vars, not code changes:** `YOLO_MODEL_PATH`
(`agents/vision/detector.py`), `PPE_MODEL_PATH` (`ppe_detector.py`), `EQUIPMENT_MODEL_PATH`
(`equipment_detector.py`), `REBAR_MODEL_PATH` (`agents/measurement/rebar_spacing.py`) each
fall back to the stock/heuristic path when unset or the file is missing — this is the same
degrade-and-say-so pattern, applied to model weights. `docs/TRAINING_PLAN.md` describes the
fine-tuning jobs that produce these files; treat its class-taxonomy/env-var claims as a plan,
not shipped state, and verify against the code above before relying on either.

**Frontend:** Next.js App Router, one route dir per view under
`frontend/engineer-dashboard/src/app/`. All backend calls go through `src/lib/api.ts` —
use it rather than inlining `NEXT_PUBLIC_API_URL`. Each frontend carries its own
`AGENTS.md` (loaded via `CLAUDE.md` → `@AGENTS.md`) with a hard rule: this Next.js
(16.x) and Expo (SDK 54/57) differ from training data — read
`node_modules/next/dist/docs/` and the versioned Expo docs before writing code there.

## Conventions

- Long explanatory docstrings/comments recording *why* a decision was made (and what broke
  before) are intentional. Update them when the reasoning changes; don't strip them.
- New SQLAlchemy models must be imported in `api/main.py`'s `lifespan` so `create_all`
  registers them on the shared `Base` from `models/zones.py`.
- Ultralytics YOLO models are AGPL-3.0; the rest of the stack is permissive. Keep the
  licence table in README.md accurate if you change detectors.
