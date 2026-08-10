"""
The 10-agent swarm, as an actual graph.

Until now the ten agents existed as ten independent modules that the API called
one at a time from whichever route happened to need them. The architecture
diagram in the pitch deck -- vision and voice lanes running in parallel,
compliance conditionally routing to the RFI drafter, everything converging on
notification and then memory -- was drawn but never executed. Nothing in the
system ever ran the loop end to end, so nothing could show a judge that it runs.

This module is that loop, built as a LangGraph `StateGraph`:

    START ─> 5 Voice ─> 1 Vision ─┬─> 2 Measurement ─┬─> 3 Compliance ─┐
                                  └─> 4 Hazard ──────┘                 │
                                     (parallel)          (join)        │
                                                                       │
                          ┌────────────────────────────────────────────┘
                          │ deviation or query?
                          ├── no ──────────────────────────────┐
                          └── yes ─> 7 Knowledge ─┬── no RFI ───┤
                                                  └─> 6 RFI ────┤
                                                                ↓
                                                        8 Notification
                                                                ↓
                                                           9 Memory
                                                                ↓
                                                          10 Learning ─> END

WHY LANGGRAPH AND NOT A FOR-LOOP. Three things a loop would not give us:

  - Real parallelism across lanes. Measurement (2) and Hazard (4) are
    independent given Vision's output and run in the same superstep. On a frame
    with people in it that is a genuine wall-clock saving, not a diagram.
  - Conditional routing as data. `route_after_compliance` returns the name of
    the next node, and that decision is recorded in the trace. The judge sees
    *why* the RFI drafter fired, not just that it did.
  - A fan-in that joins exactly once. Measurement and Hazard both feed
    Compliance; in Pregel semantics a node runs once per triggering channel, so
    a naive join runs Compliance twice. Compliance is declared `defer=True`,
    which holds it until both branches have settled.

TOPOLOGY NOTE -- WHY THE VOICE LANE IS NOT PARALLEL. The pitch diagram runs the
voice lane alongside the vision lane, and the first version of this graph did
too, with Notification as a deferred four-predecessor join. It double-fired: one
frame dispatched two alerts and wrote two inspections. `defer` resolves against
the tasks pending *at that moment*, and its reachability check does not follow
conditional edges through another deferred node -- so Notification was released
while the RFI branch was still to come, then triggered again when it arrived.
tests/unit/test_orchestrator.py::test_no_node_fires_twice_on_fan_in is the test
that caught it and is the reason the shape changed.

The fix is structural rather than a guard: exactly one predecessor of
Notification can fire on any given run, because the paths into it are mutually
exclusive conditional branches. Voice became a sequential preamble instead of a
parallel lane. The cost is real but small -- Voice returns in well under a
millisecond when there is no audio, and when there IS audio the transcript has
to exist before retrieval can use it anyway, so the lanes could never truly
overlap where it mattered. The cost of the alternative was duplicate site
alerts, which is not a trade worth making for a prettier diagram. Measurement
and Hazard still run genuinely in parallel, which is where the wall-clock saving
actually was.

WHAT THE NODES DO NOT DO. Every node delegates to the agent module that already
existed. Nothing here re-implements detection, measurement, retrieval or
dispatch; if a node looks thin, that is the point. What this module adds is
sequencing, mode selection, and the trace.

THE TRACE IS THE PRODUCT. Each node records status, wall-clock duration, the
backend that actually served it, and a one-line summary, and emits that live
over the event bus. `status` is one of:

    ok        the agent ran and produced a result
    skipped   the agent was deliberately not applicable -- always with a reason
    error     the agent raised; the run continues, the failure is visible

A node that cannot do its job returns `skipped` or `error`. It never returns a
plausible-looking result, because a fabricated measurement reaching Agent 3
becomes a real STOP WORK on a deviation that does not exist.
"""

from __future__ import annotations

import asyncio
import base64
import operator
import os
import time
import uuid
from typing import Annotated, Any, Awaitable, Callable, Optional, TypedDict

import numpy as np

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

# ---------------------------------------------------------------------------
# Node registry — the single source of truth for the diagram
# ---------------------------------------------------------------------------
#
# The frontend renders the graph from GET /api/v1/orchestrator/graph, which is
# built from these two structures. Adding an agent here changes the picture; the
# diagram cannot drift out of sync with the code because it is not drawn twice.

AGENTS: list[dict] = [
    {"id": "agent1_vision",       "n": 1,  "label": "Vision Ingestion",   "lane": "vision",
     "desc": "Detects people, PPE, pose and equipment in the frame."},
    {"id": "agent2_measurement",  "n": 2,  "label": "Measurement",        "lane": "vision",
     "desc": "Converts pixels to millimetres and measures spacing."},
    {"id": "agent3_compliance",   "n": 3,  "label": "Compliance",         "lane": "vision",
     "desc": "Compares the measurement against the stored project spec."},
    {"id": "agent4_hazard",       "n": 4,  "label": "Hazard / Safety",    "lane": "vision",
     "desc": "Scores PPE violations, falls and struck-by risk."},
    {"id": "agent5_voice",        "n": 5,  "label": "Voice / NLP",        "lane": "voice",
     "desc": "Transcribes the worker's spoken query."},
    {"id": "agent7_knowledge",    "n": 7,  "label": "Knowledge Retrieval", "lane": "reason",
     "desc": "Retrieves the governing clause from the indexed specs."},
    {"id": "agent6_rfi",          "n": 6,  "label": "RFI Drafter",        "lane": "reason",
     "desc": "Drafts the RFI, citing the retrieved passage."},
    {"id": "agent8_notification", "n": 8,  "label": "Notification",       "lane": "output",
     "desc": "Routes the alert and speaks the verdict back to the worker."},
    {"id": "agent9_memory",       "n": 9,  "label": "Project Memory",     "lane": "output",
     "desc": "Writes the incident to the knowledge graph."},
    {"id": "agent10_learning",    "n": 10, "label": "Learning / Predictive", "lane": "output",
     "desc": "Surfaces repeat patterns for this zone."},
]

AGENT_BY_ID = {a["id"]: a for a in AGENTS}

# (source, target, kind). "conditional" edges are the ones a router decides at
# runtime; the UI draws them dashed and marks which way the run actually went.
EDGES: list[tuple[str, str, str]] = [
    ("START", "agent5_voice", "always"),
    ("agent5_voice", "agent1_vision", "always"),
    ("agent1_vision", "agent2_measurement", "always"),
    ("agent1_vision", "agent4_hazard", "always"),
    ("agent2_measurement", "agent3_compliance", "always"),
    ("agent4_hazard", "agent3_compliance", "always"),
    ("agent3_compliance", "agent7_knowledge", "conditional"),
    ("agent3_compliance", "agent8_notification", "conditional"),
    ("agent7_knowledge", "agent6_rfi", "conditional"),
    ("agent7_knowledge", "agent8_notification", "conditional"),
    ("agent6_rfi", "agent8_notification", "always"),
    ("agent8_notification", "agent9_memory", "always"),
    ("agent9_memory", "agent10_learning", "always"),
    ("agent10_learning", "END", "always"),
]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class RunState(TypedDict, total=False):
    # inputs
    run_id: str
    mode: str                 # "cloud" | "edge"
    worker_id: str
    zone_id: str
    project_id: str
    frame_b64: Optional[str]
    audio_b64: Optional[str]
    audio_filename: str
    query: Optional[str]
    spec_override: Optional[dict]
    language: str
    allow_depth: bool
    started_at: float

    # per-agent output
    vision: dict
    measurement: dict
    compliance: dict
    hazard: dict
    voice: dict
    knowledge: dict
    rfi: dict
    notification: dict
    memory: dict
    prediction: dict

    # Two nodes can finish in the same superstep, so these must be reducers
    # rather than plain assignment or one branch silently overwrites the other.
    trace: Annotated[list, operator.add]
    routes: Annotated[list, operator.add]


EventHook = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Node plumbing
# ---------------------------------------------------------------------------

class Skip(Exception):
    """Raised by a node that is deliberately not applicable to this run."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _hook(config) -> Optional[EventHook]:
    try:
        return (config or {}).get("configurable", {}).get("on_event")
    except AttributeError:
        return None


async def _emit(config, payload: dict) -> None:
    hook = _hook(config)
    if hook is None:
        return
    try:
        await hook(payload)
    except Exception as e:
        # A dashboard that has disconnected must never take the pipeline with it.
        print(f"[orchestrator] event hook failed: {e}")


def node(node_id: str):
    """Wrap an agent call with timing, error containment and live tracing.

    Errors are caught by design. One agent failing -- Neo4j down, no Gemini key
    -- must not abort the other nine, or a single missing service takes the whole
    demo with it. The failure lands in the trace as `error` and stays visible.
    """
    meta = AGENT_BY_ID[node_id]

    def decorator(fn):
        async def wrapper(state: RunState, config=None):
            t0 = time.perf_counter()
            started_offset = int((time.time() - state.get("started_at", time.time())) * 1000)

            await _emit(config, {"type": "node_start", "run_id": state.get("run_id"),
                                 "node": node_id, "agent": meta["n"],
                                 "label": meta["label"], "at_ms": started_offset})

            status, error, result = "ok", None, {}
            try:
                result = await fn(state, config) or {}
            except Skip as s:
                status, result = "skipped", {"status": "skipped", "reason": s.reason}
            except Exception as e:  # noqa: BLE001 — see docstring
                status, error = "error", f"{type(e).__name__}: {e}"
                result = {"status": "error", "error": error}
                import traceback
                traceback.print_exc()

            duration = int((time.perf_counter() - t0) * 1000)
            record = {
                "node": node_id,
                "agent": meta["n"],
                "label": meta["label"],
                "lane": meta["lane"],
                "status": status,
                "at_ms": started_offset,
                "duration_ms": duration,
                "backend": result.get("backend"),
                "summary": result.get("summary") or result.get("reason") or error or "",
                "error": error,
            }

            await _emit(config, {"type": "node_end", "run_id": state.get("run_id"), **record})

            key = result.pop("_state_key", node_id.split("_", 1)[1])
            payload = dict(result)
            payload.setdefault("status", status)
            payload["duration_ms"] = duration
            return {key: payload, "trace": [record]}

        wrapper.__name__ = node_id
        return wrapper

    return decorator


def _decode_frame(state: RunState) -> np.ndarray:
    """base64 JPEG -> BGR ndarray. Raises Skip when there is no frame at all."""
    import cv2

    b64 = state.get("frame_b64")
    if not b64:
        raise Skip("no frame supplied in this run")
    if "," in b64[:64]:                       # strip a data: URL prefix
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise Skip("frame did not decode as an image")
    return img


def _encode_jpeg(image: np.ndarray, quality: int = 80) -> Optional[str]:
    import cv2
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf).decode() if ok else None


def _measured_mm(measurement: dict) -> Optional[float]:
    """Pull the millimetre value out of an Agent 2 measurement.

    Agent 2 emits spacing results as `{"value": ..., "unit": "mm"}` while the
    object-dimensioning path emits `value_mm`. Reading only one of them made
    Agent 3 skip every spacing result with "carried no value_mm" while Agent 2
    had in fact measured it. The unit is checked rather than assumed -- feeding
    a metre value into a millimetre tolerance is a silent 1000x error that still
    produces a confident-looking FAIL.
    """
    if not isinstance(measurement, dict):
        return None
    if measurement.get("value_mm") is not None:
        return float(measurement["value_mm"])
    value, unit = measurement.get("value"), (measurement.get("unit") or "mm").lower()
    if value is None:
        return None
    if unit == "mm":
        return float(value)
    if unit in ("m", "metre", "meter"):
        return float(value) * 1000.0
    if unit == "cm":
        return float(value) * 10.0
    return None


# ---------------------------------------------------------------------------
# Agent 1 — Vision Ingestion
# ---------------------------------------------------------------------------

_vision_pipeline = None


def _get_vision_pipeline():
    global _vision_pipeline
    if _vision_pipeline is None:
        from agents.vision.detector import VisionPipeline
        _vision_pipeline = VisionPipeline()
    return _vision_pipeline


@node("agent1_vision")
async def agent1_vision(state: RunState, config) -> dict:
    """Detect what is in the frame.

    This is where Cloud and Edge genuinely diverge, and the difference is a
    different set of weights on a different runtime -- not a flag that changes a
    label. Cloud runs the full PyTorch stack (YOLO11n + PPE classifier + pose +
    hazard fusion). Edge runs the INT8 ONNX export through onnxruntime, the same
    build that ships as onnxruntime-android, so what executes here is what would
    execute on the phone. The reported `backend` names which one served, and the
    execution provider comes straight from the loaded session.
    """
    image = _decode_frame(state)

    if state.get("mode") == "edge":
        from agents.edge.runtime import get_detector
        detector = get_detector()
        if not detector.ready:                      # `ready` is a property
            raise Skip(f"edge ONNX model not loaded: {detector.load_error or 'unknown'} "
                       "— export it with python -m agents.vision.onnx_exporter, "
                       "or use Cloud mode")

        result = await asyncio.to_thread(detector.detect, image)
        payload = result.as_dict()
        persons = payload.get("person_count", 0)
        return {
            "backend": f"onnx:{payload.get('model')}@{payload.get('provider')}",
            "summary": f"{persons} person(s), {payload['timing_ms']['total']:.0f}ms on device",
            "person_count": persons,
            "detections": payload.get("detections", []),
            "edge_hazards": payload.get("hazards", []),
            "timing_ms": payload.get("timing_ms", {}),
            "assets_detected": [],
        }

    pipeline = _get_vision_pipeline()
    result = await asyncio.to_thread(pipeline.analyze_ndarray, image)

    annotated = result.pop("annotated_frame", None)
    if annotated is not None:
        result["annotated_frame_b64"] = _encode_jpeg(annotated)

    assets = result.get("assets_detected", [])
    persons = [a for a in assets if a.get("asset_type") == "person"]
    result["person_count"] = len(persons)
    result["backend"] = "yolo11n+ppe+pose (torch)"
    result["summary"] = f"{len(persons)} person(s), {len(assets)} object(s) detected"
    return result


# ---------------------------------------------------------------------------
# Agent 2 — Measurement
# ---------------------------------------------------------------------------

_measurement_engine = None


def _get_measurement_engine():
    global _measurement_engine
    if _measurement_engine is None:
        from agents.measurement.estimator import MeasurementEngine
        _measurement_engine = MeasurementEngine()
    return _measurement_engine


@node("agent2_measurement")
async def agent2_measurement(state: RunState, config) -> dict:
    """Measure real-world spacing in the frame.

    Edge mode disables the depth rung of the calibration ladder. Metric3D costs
    ~5.6s of CPU per frame, which is not something a phone does in a live loop.
    The consequence is stated rather than hidden: without a marker in frame, Edge
    mode reports `uncalibrated` and no measurement is produced.
    """
    image = _decode_frame(state)
    engine = _get_measurement_engine()
    allow_depth = state.get("allow_depth", state.get("mode") != "edge")

    result = await asyncio.to_thread(
        engine.measure, image, "spacing", None, None, None, None, "webcam", False, allow_depth,
    )

    calib = result.get("calibration", {}) or {}
    method = calib.get("method", "none")
    result["backend"] = f"calibration:{method}" + (
        f"/{calib['depth_provider']}" if calib.get("depth_provider") else "")

    measurements = result.get("measurements", [])
    if result.get("status") == "uncalibrated":
        result["summary"] = "cannot convert pixels to mm in this frame — no measurement issued"
    elif measurements:
        first = measurements[0]
        result["summary"] = (f"{len(measurements)} measurement(s); "
                             f"{_measured_mm(first)}mm via {method}")
    else:
        result["summary"] = "calibrated, but no measurable structure in frame"
    return result


# ---------------------------------------------------------------------------
# Agent 3 — Compliance
# ---------------------------------------------------------------------------

@node("agent3_compliance")
async def agent3_compliance(state: RunState, config) -> dict:
    """Compare the measurement against the project's stored spec.

    Skips rather than guesses in two cases: no measurement to check, and no spec
    on file for this parameter. The second is the important one -- inventing a
    tolerance would produce a verdict that looks identical to a real one.
    """
    from agents.compliance import spec_registry
    from agents.compliance.validator import (
        ComplianceEngine, Measurement, Specification, ValidationRequest,
    )

    measurement = state.get("measurement") or {}
    values = measurement.get("measurements") or []
    if not values:
        raise Skip(measurement.get("summary") or "no measurement to validate")

    # Several axes can be measured in one frame; validate the one the engine is
    # most confident about rather than whichever happens to be first.
    primary = max(values, key=lambda m: float(m.get("confidence") or 0.0))
    measured_mm = _measured_mm(primary)
    if measured_mm is None:
        raise Skip(f"measurement carried no usable mm value (unit={primary.get('unit')!r})")

    # The spacing extractor is the linear-element (rebar) one, so "rebar" is a
    # reasonable hint -- but it is a hint, not a classification. Nothing in a
    # spacing measurement proves the bars are rebar rather than conduit, and the
    # registry treats it accordingly.
    spec = spec_registry.resolve(
        parameter="spacing",
        zone_id=state.get("zone_id", ""),
        asset_type="rebar",
        override=state.get("spec_override"),
    )
    if spec is None:
        return {
            "status": "no_spec",
            "backend": "spec_registry",
            "summary": ("no spec on file for spacing in zone "
                        f"{state.get('zone_id') or '?'} — verdict withheld"),
            "remedy": "add an entry to data/specs.json, or pass spec_override on the run",
        }

    req = ValidationRequest(
        observation_id=state.get("run_id", str(uuid.uuid4())),
        asset_id=f"{state.get('zone_id', 'ZONE')}-{primary.get('type', 'spacing')}",
        zone_id=state.get("zone_id", ""),
        measurement=Measurement(
            parameter="spacing",
            measured_value=float(measured_mm),
            unit="mm",
            confidence=float(primary.get("confidence", 0.0) or 0.0),
        ),
        specification=Specification(
            spec_id=spec.spec_id,
            expected_value=spec.expected_value,
            tolerance_min=spec.tolerance_min,
            tolerance_max=spec.tolerance_max,
            unit=spec.unit,
            standard_ref=spec.standard_ref,
        ),
    )

    result = await ComplianceEngine().validate(req)
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    elif hasattr(result, "dict"):
        result = result.dict()
    result = dict(result)

    verdict = result.get("result") or result.get("status") or "unknown"
    result["spec_source"] = spec.source
    result["spec"] = spec.as_dict()
    verdict = str(verdict).upper()
    result["backend"] = f"rule_engine (spec {spec.spec_id} from {spec.source})"
    result["summary"] = (f"{verdict}: measured {measured_mm}mm vs "
                         f"{spec.expected_value}mm [{spec.tolerance_min}–{spec.tolerance_max}]")
    result["verdict"] = verdict
    result["measured_mm"] = measured_mm
    result["deviation_found"] = verdict in ("FAIL", "DEVIATION", "FAILED")
    # UNCERTAIN is the engine's answer when measurement confidence is below 0.75
    # -- which is every depth-derived measurement, since that path is only good
    # to ~15%. It is deliberately NOT folded into either PASS or FAIL: calling it
    # a pass hides an out-of-tolerance reading, and calling it a failure hands
    # Agent 5 a STOP WORK built on a number the engine does not trust.
    result["uncertain"] = verdict == "UNCERTAIN"
    return result


# ---------------------------------------------------------------------------
# Agent 4 — Hazard / Safety
# ---------------------------------------------------------------------------

@node("agent4_hazard")
async def agent4_hazard(state: RunState, config) -> dict:
    """Turn Agent 1's per-person assessments into one zone-level verdict.

    In Cloud mode the per-person hazard fusion already ran inside the vision
    pipeline; this aggregates it. In Edge mode the geometric on-device rules
    (fall aspect-ratio, proximity) are what is available, and that is reported
    as the backend so the two are never confused.
    """
    vision = state.get("vision") or {}
    if vision.get("status") in ("skipped", "error"):
        raise Skip("vision produced nothing to assess")

    if state.get("mode") == "edge":
        hazards = vision.get("edge_hazards", []) or []
        severity = "critical" if hazards else "normal"
        return {
            "backend": "edge geometric rules (on-device)",
            "hazards": hazards,
            "severity": severity,
            "hazard_count": len(hazards),
            "summary": (f"{len(hazards)} hazard(s) flagged on device"
                        if hazards else "no on-device hazard triggered"),
        }

    zone = vision.get("zone_summary", {}) or {}
    checks = vision.get("compliance_checks", []) or []
    falls = vision.get("fall_events", []) or []
    struck = vision.get("struck_by_events", []) or []

    violations = [c for c in checks if c.get("ppe_score", 1.0) < 1.0]
    risk_level = zone.get("zone_risk_level", "normal")

    severity = "critical" if (falls or struck) else (
        "high" if violations else risk_level)

    parts = []
    if violations:
        parts.append(f"{len(violations)} PPE violation(s)")
    if falls:
        parts.append(f"{len(falls)} fall event(s)")
    if struck:
        parts.append(f"{len(struck)} struck-by risk(s)")

    return {
        "backend": "hazard_analyzer (pose + PPE fusion)",
        "severity": severity,
        "risk_level": risk_level,
        "risk_score": zone.get("zone_risk_score", 0),
        "ppe_violations": violations,
        "fall_events": falls,
        "struck_by_events": struck,
        "hazard_found": bool(violations or falls or struck),
        "summary": ", ".join(parts) if parts else "no hazard detected",
    }


# ---------------------------------------------------------------------------
# Agent 5 — Voice / NLP
# ---------------------------------------------------------------------------

@node("agent5_voice")
async def agent5_voice(state: RunState, config) -> dict:
    """Transcribe the worker's spoken query, if one was captured.

    A run with no audio is the normal case -- the pitch's whole point is that
    the system works without the worker saying anything -- so an absent
    recording is `skipped`, not an error. A typed query is accepted as an
    equivalent input and labelled as such rather than being passed off as
    speech.
    """
    audio_b64 = state.get("audio_b64")
    typed = (state.get("query") or "").strip()

    if not audio_b64:
        if typed:
            return {"backend": "typed input (no audio)", "transcript": typed,
                    "source": "typed", "summary": f'typed query: "{typed[:60]}"'}
        raise Skip("no audio and no typed query in this run")

    from agents.voice.transcriber import VoiceAgent

    raw = base64.b64decode(audio_b64.split(",", 1)[-1])
    result = await VoiceAgent().transcribe(raw, state.get("audio_filename", "audio.webm"))
    transcript = (result or {}).get("transcript", "") if isinstance(result, dict) else str(result)

    return {
        "backend": "whisper-large-v3-turbo (Groq)",
        "transcript": transcript,
        "source": "speech",
        "raw": result if isinstance(result, dict) else {},
        "summary": f'heard: "{(transcript or "")[:60]}"' if transcript else "no speech recognised",
    }


# ---------------------------------------------------------------------------
# Agent 7 — Knowledge Retrieval  (runs before 6; the drafter needs the citation)
# ---------------------------------------------------------------------------

@node("agent7_knowledge")
async def agent7_knowledge(state: RunState, config) -> dict:
    """Retrieve the governing clause from the indexed spec corpus.

    Returns zero citations rather than a synthesised passage when nothing scores
    above threshold. Agent 6 then drafts an explicitly uncited RFI. A drafted
    clause that reads like a real one is the single most damaging thing this
    system could produce, because it is exactly what an engineer would approve
    without checking.
    """
    compliance = state.get("compliance") or {}
    voice = state.get("voice") or {}

    query_parts = []
    if compliance.get("deviation_found"):
        spec = compliance.get("spec", {})
        query_parts.append(f"{spec.get('parameter', 'spacing')} tolerance "
                           f"{spec.get('standard_ref', '')}")
    if voice.get("transcript"):
        query_parts.append(voice["transcript"])

    query = " ".join(p for p in query_parts if p).strip()
    if not query:
        raise Skip("nothing to look up — no deviation and no worker query")

    import sys
    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
    if api_dir not in sys.path:
        sys.path.append(api_dir)
    from api.routes.rfi_draft import _cite

    citations = await _cite(query, state.get("project_id", "default-project"), top_k=3)
    cites = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in citations]

    return {
        "backend": "qdrant vector search",
        "query": query,
        "citations": cites,
        "summary": (f"{len(cites)} clause(s) retrieved for “{query[:40]}”"
                    if cites else "no passage scored above the citation threshold"),
    }


# ---------------------------------------------------------------------------
# Agent 6 — RFI Drafter
# ---------------------------------------------------------------------------

@node("agent6_rfi")
async def agent6_rfi(state: RunState, config) -> dict:
    """Draft the RFI for the deviation, citing what Agent 7 actually retrieved."""
    compliance = state.get("compliance") or {}
    if not compliance.get("deviation_found"):
        raise Skip("no deviation — nothing to raise an RFI about")

    knowledge = state.get("knowledge") or {}
    citations = knowledge.get("citations", []) or []
    spec = compliance.get("spec", {}) or {}

    import sys
    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
    if api_dir not in sys.path:
        sys.path.append(api_dir)
    from api.routes.rfi_draft import Citation, _fallback_body

    # Key names must match what _fallback_body reads (`zone`, `measured`,
    # `expected`, `asset_type`). Getting them wrong does not error -- it drafts a
    # grammatical RFI that omits the measurement entirely, which is the one thing
    # the RFI exists to communicate.
    unit = spec.get("unit", "mm")
    measured_mm = compliance.get("measured_mm")
    deviation_pct = compliance.get("deviation_pct")
    if deviation_pct is None and measured_mm is not None and spec.get("expected_value"):
        expected = float(spec["expected_value"])
        deviation_pct = abs(measured_mm - expected) / expected * 100.0

    ctx = {
        "zone": state.get("zone_id", ""),
        "zone_code": state.get("zone_id", ""),
        "asset_type": spec.get("parameter", "spacing"),
        "issue_type": "measurement_deviation",
        "description": compliance.get("summary", ""),
        "measured": f"{measured_mm}{unit}" if measured_mm is not None else None,
        "expected": (f"{spec.get('expected_value')}{unit} "
                     f"({spec.get('tolerance_min')}–{spec.get('tolerance_max')}{unit})")
                    if spec.get("expected_value") is not None else None,
        "deviation_pct": deviation_pct,
        "severity": compliance.get("severity", "medium"),
        "standard_ref": spec.get("standard_ref"),
    }

    body = _fallback_body(ctx, [Citation(**c) for c in citations])

    return {
        "backend": "deterministic template + retrieved citations",
        "subject": f"Spacing deviation in zone {state.get('zone_id', '?')}",
        "body": body,
        "citations": citations,
        "cited": bool(citations),
        "context": ctx,
        "summary": (f"RFI drafted with {len(citations)} citation(s)"
                    if citations else "RFI drafted — NO citation found, flagged uncited"),
    }


# ---------------------------------------------------------------------------
# Agent 8 — Notification (+ the spoken reply)
# ---------------------------------------------------------------------------

@node("agent8_notification")
async def agent8_notification(state: RunState, config) -> dict:
    """Route the alert and synthesise the reply the worker actually hears.

    This is the node that closes the hands-free loop, so it runs on every path,
    including the all-clear. TTS failure is reported, never silently swallowed:
    a worker who hears nothing must not be indistinguishable from a worker who
    was told everything is fine.
    """
    from agents.notification.router import NotificationEvent, NotificationRouter
    from agents.voice import tts as tts_mod

    compliance = state.get("compliance") or {}
    hazard = state.get("hazard") or {}
    rfi = state.get("rfi") or {}
    voice = state.get("voice") or {}

    deviation = bool(compliance.get("deviation_found"))
    hazard_found = bool(hazard.get("hazard_found") or hazard.get("hazard_count"))

    if hazard_found:
        severity, event_type = hazard.get("severity", "high"), "hazard_detected"
        spoken = f"Safety alert. {hazard.get('summary', 'Hazard detected')}."
    elif deviation:
        severity, event_type = compliance.get("severity", "high"), "measurement_deviation"
        spoken = f"Deviation found. {compliance.get('summary', '')}."
        if rfi.get("status") == "ok":
            spoken += " An R F I has been drafted for engineer approval."
    elif compliance.get("uncertain"):
        # Must not collapse into all-clear. The measurement can be far out of
        # tolerance and still land here -- what is missing is confidence, not
        # deviation, and the worker is the one who can fix that by placing a
        # marker in frame.
        severity, event_type = "warning", "measurement_uncertain"
        measured = compliance.get("measured_mm")
        spec = compliance.get("spec", {})
        spoken = (f"Measurement inconclusive. I read {measured:.0f} millimetres "
                  f"against a spec of {spec.get('expected_value')}, but confidence is "
                  f"too low to call it. Place a marker in frame and scan again."
                  if measured is not None else
                  "Measurement inconclusive. Confidence too low to issue a verdict.")
    elif voice.get("transcript"):
        severity, event_type = "info", "worker_query"
        cites = (state.get("knowledge") or {}).get("citations", [])
        spoken = (f"From the project specs: {cites[0]['excerpt'][:240]}"
                  if cites else "I could not find that in the indexed project specs.")
    else:
        severity, event_type = "info", "all_clear"
        spoken = "Scan complete. No deviation or hazard detected."

    event = NotificationEvent(
        notification_id=state.get("run_id", str(uuid.uuid4())),
        event_type=event_type,
        severity=str(severity),
        zone_id=state.get("zone_id"),
        worker_id=state.get("worker_id"),
        message=spoken,
        evidence={"compliance": compliance.get("summary", ""),
                  "hazard": hazard.get("summary", "")},
    )

    dispatch: dict = {}
    try:
        dispatch = await NotificationRouter().dispatch(event)
    except Exception as e:
        dispatch = {"error": f"{type(e).__name__}: {e}"}

    audio_b64, tts_backend, tts_error = None, None, None
    try:
        audio_b64, tts_backend = await asyncio.to_thread(
            tts_mod.synthesize, spoken, state.get("mode", "cloud"))
    except Exception as e:
        tts_error = f"{type(e).__name__}: {e}"

    return {
        "backend": f"notification_router + tts:{tts_backend or 'unavailable'}",
        "event_type": event_type,
        "severity": severity,
        "spoken_text": spoken,
        "audio_base64": audio_b64,
        "tts_backend": tts_backend,
        "tts_error": tts_error,
        "spoken_ok": bool(audio_b64),
        "dispatch": dispatch,
        "summary": (f"{event_type} ({severity}) — "
                    + ("spoken via " + tts_backend if audio_b64
                       else f"NOT spoken ({tts_error or 'no TTS backend'})")),
    }


# ---------------------------------------------------------------------------
# Agent 9 — Project Memory
# ---------------------------------------------------------------------------

@node("agent9_memory")
async def agent9_memory(state: RunState, config) -> dict:
    """Persist the incident so Agent 10 has history to learn from."""
    from agents.knowledge_graph.writer import write_inspection

    compliance = state.get("compliance") or {}
    hazard = state.get("hazard") or {}
    notification = state.get("notification") or {}

    verdict = (compliance.get("result") or compliance.get("status") or "").upper()
    if verdict not in ("PASS", "FAIL", "UNCERTAIN"):
        verdict = "FAIL" if hazard.get("hazard_found") else "PASS"

    asset_id = f"{state.get('zone_id', 'ZONE')}-rebar"
    written = await write_inspection(
        zone_id=state.get("zone_id", ""),
        asset_id=asset_id,
        result=verdict,
        confidence=float(compliance.get("confidence", 0.0) or 0.0),
        asset_type_hint="rebar spacing",
        inspector_id=f"orchestrator:{state.get('worker_id', 'unknown')}",
    )

    interaction_id = None
    try:
        import sys
        api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
        if api_dir not in sys.path:
            sys.path.append(api_dir)
        from api.routes.interactions import record_interaction
        fired = [t["node"] for t in (state.get("trace") or []) if t.get("status") == "ok"]
        interaction_id = await record_interaction(
            kind=notification.get("event_type", "scan"),
            project_id=state.get("project_id", "default-project"),
            zone_code=state.get("zone_id", ""),
            worker_id=state.get("worker_id", ""),
            query=(state.get("voice") or {}).get("transcript", "") or "orchestrated frame scan",
            result=notification.get("spoken_text", ""),
            verdict=verdict,
            severity=str(notification.get("severity", "")),
            confidence=float(compliance.get("confidence", 0.0) or 0.0),
            agent_chain=" -> ".join(fired),
            evidence_ref=state.get("run_id"),
        )
    except Exception as e:
        print(f"[orchestrator] interaction log skipped: {e}")

    return {
        "backend": "neo4j knowledge graph" if written else "neo4j unreachable (logged locally)",
        "graph_written": written,
        "verdict_recorded": verdict,
        "asset_id": asset_id,
        "interaction_id": str(interaction_id) if interaction_id else None,
        "summary": (f"{verdict} recorded against {asset_id}" if written
                    else f"{verdict} NOT written — knowledge graph unreachable"),
    }


# ---------------------------------------------------------------------------
# Agent 10 — Learning / Predictive
# ---------------------------------------------------------------------------

@node("agent10_learning")
async def agent10_learning(state: RunState, config) -> dict:
    """Surface repeat patterns for this zone.

    Explicitly a frequency count over recorded history, not a trained predictor.
    Follow.md section 5 asks for exactly this and asks that it be labelled, so
    `method: "heuristic"` travels in the payload and the UI renders it -- the
    honesty is in the response, not in a comment nobody sees.

    Counts come from the issue table rather than Neo4j on purpose: this must
    still say something true when the graph is down, and `get_zone_risk_score`
    is a synchronous Neo4j-session query that cannot be called from here anyway.
    """
    import sys
    from datetime import datetime, timedelta

    api_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../api"))
    if api_dir not in sys.path:
        sys.path.append(api_dir)

    from sqlalchemy import select
    from db import async_session
    from models.issues import FieldIssue

    zone = state.get("zone_id", "")
    if not zone:
        raise Skip("no zone on this run — nothing to correlate against")

    since = datetime.utcnow() - timedelta(days=30)
    async with async_session() as session:
        rows = (await session.execute(
            select(FieldIssue).where(
                FieldIssue.zone_code == zone,
                FieldIssue.created_at >= since,
            )
        )).scalars().all()

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r.issue_type or "unspecified"] = by_type.get(r.issue_type or "unspecified", 0) + 1

    ranked = sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0] if ranked else None
    open_count = sum(1 for r in rows if (r.status or "") == "open")

    if not rows:
        summary = f"no recorded history for zone {zone} in 30 days — nothing to predict from"
    elif top and top[1] >= 2:
        summary = (f"zone {zone}: {top[0]} recurred {top[1]}x in 30 days "
                   f"({open_count} still open) — likely to repeat")
    else:
        summary = (f"zone {zone}: {len(rows)} issue(s) in 30 days, no repeating pattern yet")

    return {
        "backend": "frequency heuristic over recorded issues (30d)",
        "method": "heuristic",
        "method_note": ("Frequency count over recorded issues. Not a trained "
                        "predictive model — labelled as a heuristic by design."),
        "zone_id": zone,
        "window_days": 30,
        "issue_count": len(rows),
        "open_count": open_count,
        "by_type": dict(ranked),
        "top_pattern": {"type": top[0], "count": top[1]} if top else None,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Routers — the conditional edges, and the reason for each decision
# ---------------------------------------------------------------------------

def route_after_compliance(state: RunState) -> str:
    """Retrieval is worth its latency only if there is something to look up.

    Both triggers are checked here rather than in two separate routers: Voice
    runs before this point, so its transcript is already in state, and a single
    decision point keeps Notification reachable by exactly one path per run.
    """
    compliance = state.get("compliance") or {}
    voice = state.get("voice") or {}
    if compliance.get("deviation_found") or (voice.get("transcript") or "").strip():
        return "agent7_knowledge"
    return "agent8_notification"


def route_after_knowledge(state: RunState) -> str:
    compliance = state.get("compliance") or {}
    if compliance.get("deviation_found"):
        return "agent6_rfi"
    return "agent8_notification"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

_compiled = None


def build_graph():
    """Compile the graph once. Node functions are stateless; models are cached
    in their own module-level singletons, so one compiled graph is reusable."""
    global _compiled
    if _compiled is not None:
        return _compiled

    g = StateGraph(RunState)

    g.add_node("agent5_voice", agent5_voice)
    g.add_node("agent1_vision", agent1_vision)
    g.add_node("agent2_measurement", agent2_measurement)
    g.add_node("agent4_hazard", agent4_hazard)
    # The only join in the graph, and the only deferred node. Both predecessors
    # are plain nodes at the same depth, which is the case `defer` handles
    # reliably -- see the topology note in the module docstring for the case it
    # does not.
    g.add_node("agent3_compliance", agent3_compliance, defer=True)
    g.add_node("agent7_knowledge", agent7_knowledge)
    g.add_node("agent6_rfi", agent6_rfi)
    g.add_node("agent8_notification", agent8_notification)
    g.add_node("agent9_memory", agent9_memory)
    g.add_node("agent10_learning", agent10_learning)

    g.add_edge(START, "agent5_voice")
    g.add_edge("agent5_voice", "agent1_vision")

    # The genuine parallelism: measurement and hazard are independent given the
    # frame, and run in the same superstep.
    g.add_edge("agent1_vision", "agent2_measurement")
    g.add_edge("agent1_vision", "agent4_hazard")
    g.add_edge("agent2_measurement", "agent3_compliance")
    g.add_edge("agent4_hazard", "agent3_compliance")

    g.add_conditional_edges("agent3_compliance", route_after_compliance,
                            {"agent7_knowledge": "agent7_knowledge",
                             "agent8_notification": "agent8_notification"})
    g.add_conditional_edges("agent7_knowledge", route_after_knowledge,
                            {"agent6_rfi": "agent6_rfi",
                             "agent8_notification": "agent8_notification"})

    g.add_edge("agent6_rfi", "agent8_notification")
    g.add_edge("agent8_notification", "agent9_memory")
    g.add_edge("agent9_memory", "agent10_learning")
    g.add_edge("agent10_learning", END)

    _compiled = g.compile(checkpointer=MemorySaver())
    return _compiled


def graph_topology() -> dict:
    """The diagram, as data. The UI renders from this so it cannot drift."""
    return {
        "nodes": AGENTS,
        "edges": [{"source": s, "target": t, "kind": k} for s, t, k in EDGES],
        "lanes": [
            {"id": "vision", "label": "Vision lane"},
            {"id": "voice", "label": "Voice lane"},
            {"id": "reason", "label": "Reasoning"},
            {"id": "output", "label": "Output & memory"},
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_pipeline(*,
                       frame_b64: Optional[str] = None,
                       audio_b64: Optional[str] = None,
                       audio_filename: str = "audio.webm",
                       query: Optional[str] = None,
                       mode: str = "cloud",
                       worker_id: str = "W-001",
                       zone_id: str = "A12",
                       project_id: str = "default-project",
                       language: str = "en",
                       spec_override: Optional[dict] = None,
                       allow_depth: Optional[bool] = None,
                       on_event: Optional[EventHook] = None,
                       run_id: Optional[str] = None) -> dict:
    """Run one frame (and optional utterance) through all ten agents."""
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    started = time.time()
    mode = "edge" if str(mode).lower() in ("edge", "offline") else "cloud"

    state: RunState = {
        "run_id": run_id,
        "mode": mode,
        "worker_id": worker_id,
        "zone_id": zone_id,
        "project_id": project_id,
        "frame_b64": frame_b64,
        "audio_b64": audio_b64,
        "audio_filename": audio_filename,
        "query": query,
        "language": language,
        "spec_override": spec_override,
        "allow_depth": (mode != "edge") if allow_depth is None else allow_depth,
        "started_at": started,
        "trace": [],
        "routes": [],
    }

    if on_event:
        await on_event({"type": "run_start", "run_id": run_id, "mode": mode,
                        "zone_id": zone_id, "worker_id": worker_id})

    graph = build_graph()
    config = {"configurable": {"thread_id": run_id, "on_event": on_event}}

    final = await graph.ainvoke(state, config=config)

    trace = sorted(final.get("trace", []), key=lambda r: (r["at_ms"], r["agent"]))
    fired = [r for r in trace if r["status"] == "ok"]
    errors = [r for r in trace if r["status"] == "error"]

    result = {
        "run_id": run_id,
        "mode": mode,
        "zone_id": zone_id,
        "worker_id": worker_id,
        "duration_ms": int((time.time() - started) * 1000),
        "agents_fired": len(fired),
        "agents_total": len(AGENTS),
        "agents_errored": len(errors),
        "trace": trace,
        "vision": final.get("vision", {}),
        "measurement": final.get("measurement", {}),
        "compliance": final.get("compliance", {}),
        "hazard": final.get("hazard", {}),
        "voice": final.get("voice", {}),
        "knowledge": final.get("knowledge", {}),
        "rfi": final.get("rfi", {}),
        "notification": final.get("notification", {}),
        "memory": final.get("memory", {}),
        "prediction": final.get("learning", {}),
    }

    if on_event:
        await on_event({"type": "run_end", **{k: v for k, v in result.items()
                                              if k in ("run_id", "mode", "duration_ms",
                                                       "agents_fired", "agents_total",
                                                       "agents_errored")}})
    return result
