"""
Tests for the 10-agent orchestrator graph.

These are hermetic: no models, no weights, no network, no database. They cover
the properties of the *graph* rather than of the agents, because the agents have
their own tests and the graph has failure modes none of them can catch.

The one that matters most is single-fire on fan-in. Notification is reachable
from four predecessors down branches of three different lengths. In Pregel
semantics a node runs once per triggering channel update, so without `defer=True`
one frame dispatches up to four alerts and writes four inspections -- and it does
so silently, because every individual agent behaved correctly. That is exactly
the kind of bug that survives a demo and shows up as duplicate site alerts.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents.orchestrator import graph as G


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def test_every_edge_references_a_declared_node():
    """The UI draws from EDGES. An edge to a node that does not exist renders as
    a wire into empty space, and nobody notices until a demo."""
    known = set(G.AGENT_BY_ID) | {"START", "END"}
    for source, target, _kind in G.EDGES:
        assert source in known, f"edge source {source!r} is not a declared node"
        assert target in known, f"edge target {target!r} is not a declared node"


def test_all_ten_agents_are_present_and_numbered_once():
    numbers = sorted(a["n"] for a in G.AGENTS)
    assert numbers == list(range(1, 11)), f"expected agents 1-10, got {numbers}"


def test_topology_endpoint_payload_is_self_consistent():
    topo = G.graph_topology()
    node_ids = {n["id"] for n in topo["nodes"]}
    lanes = {l["id"] for l in topo["lanes"]}
    for n in topo["nodes"]:
        assert n["lane"] in lanes, f"node {n['id']} sits in undeclared lane {n['lane']}"
    for e in topo["edges"]:
        assert e["source"] in node_ids | {"START", "END"}
        assert e["target"] in node_ids | {"START", "END"}


# ---------------------------------------------------------------------------
# Execution semantics, with every agent stubbed
# ---------------------------------------------------------------------------

def _install_stubs(monkeypatch, compliance: dict, voice: dict):
    """Replace all ten agent callables, then force a rebuild of the real graph.

    The topology under test is the real one -- build_graph() is untouched. Only
    the node bodies are swapped, so what is being asserted is the wiring.
    """
    calls: dict[str, int] = {}

    def stub(node_id: str, payload: dict | None = None):
        key = node_id.split("_", 1)[1]

        async def fn(state, config=None):
            calls[node_id] = calls.get(node_id, 0) + 1
            return {key: dict(payload or {"status": "ok"}), "trace": [{
                "node": node_id, "agent": G.AGENT_BY_ID[node_id]["n"],
                "label": G.AGENT_BY_ID[node_id]["label"],
                "lane": G.AGENT_BY_ID[node_id]["lane"],
                "status": "ok", "at_ms": 0, "duration_ms": 0,
                "backend": "stub", "summary": "", "error": None,
            }]}

        fn.__name__ = node_id
        return fn

    payloads = {
        "agent3_compliance": compliance,
        "agent5_voice": voice,
    }
    for node_id in G.AGENT_BY_ID:
        monkeypatch.setattr(G, node_id, stub(node_id, payloads.get(node_id)))

    monkeypatch.setattr(G, "_compiled", None)
    return calls


def _run(state_extra: dict | None = None) -> dict:
    graph = G.build_graph()
    state = {"run_id": "test", "mode": "cloud", "zone_id": "A12",
             "started_at": 0.0, "trace": [], "routes": [], **(state_extra or {})}
    return asyncio.run(graph.ainvoke(state, config={"configurable": {"thread_id": "test"}}))


def test_no_node_fires_twice_on_fan_in(monkeypatch):
    """Notification has four predecessors on uneven branches. It must run once."""
    calls = _install_stubs(monkeypatch,
                           compliance={"status": "ok", "deviation_found": True},
                           voice={"status": "ok", "transcript": "what is the spec here"})
    _run()

    for node_id, count in calls.items():
        assert count == 1, f"{node_id} fired {count}x — fan-in is double-triggering"

    # With both a deviation and a spoken query, every agent should have run.
    assert set(calls) == set(G.AGENT_BY_ID), (
        f"expected all ten to fire, missing {set(G.AGENT_BY_ID) - set(calls)}")


def test_clean_frame_skips_the_rfi_path(monkeypatch):
    """No deviation and no query: knowledge and RFI must not run at all.

    Drafting an RFI for a compliant frame would put a fabricated deviation in
    front of an engineer with an Approve button next to it.
    """
    calls = _install_stubs(monkeypatch,
                           compliance={"status": "ok", "deviation_found": False},
                           voice={"status": "skipped"})
    _run()

    assert "agent6_rfi" not in calls, "RFI drafted with no deviation to draft it for"
    assert "agent7_knowledge" not in calls, "spec lookup ran with nothing to look up"
    # The output chain must still complete — the worker gets an all-clear.
    for required in ("agent8_notification", "agent9_memory", "agent10_learning"):
        assert calls.get(required) == 1, f"{required} did not run on a clean frame"


def test_voice_query_reaches_knowledge_without_a_deviation(monkeypatch):
    """A worker asking a question routes to retrieval, but not to RFI drafting."""
    calls = _install_stubs(monkeypatch,
                           compliance={"status": "ok", "deviation_found": False},
                           voice={"status": "ok", "transcript": "what is the rebar spacing spec"})
    _run()

    assert calls.get("agent7_knowledge") == 1, "voice query did not reach retrieval"
    assert "agent6_rfi" not in calls, "a question is not a deviation — no RFI should be drafted"


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("compliance,voice,expected", [
    ({"deviation_found": True},  {},                                    "agent7_knowledge"),
    ({"deviation_found": False}, {"transcript": "what is the spec"},    "agent7_knowledge"),
    ({"deviation_found": False}, {},                                    "agent8_notification"),
    ({},                         {"transcript": "   "},                 "agent8_notification"),
    ({"status": "skipped"},      {"status": "skipped"},                 "agent8_notification"),
])
def test_route_after_compliance(compliance, voice, expected):
    assert G.route_after_compliance({"compliance": compliance, "voice": voice}) == expected


def test_uncertain_verdict_does_not_route_to_rfi():
    """UNCERTAIN is not a deviation. Drafting an RFI from a measurement the
    engine does not trust is how a low-confidence reading becomes a STOP WORK."""
    state = {"compliance": {"verdict": "UNCERTAIN", "uncertain": True, "deviation_found": False}}
    assert G.route_after_compliance(state) == "agent8_notification"
    assert G.route_after_knowledge(state) == "agent8_notification"


# ---------------------------------------------------------------------------
# Unit boundary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measurement,expected", [
    ({"value": 150.0, "unit": "mm"}, 150.0),
    ({"value_mm": 152.5}, 152.5),
    ({"value": 0.15, "unit": "m"}, 150.0),
    ({"value": 15.0, "unit": "cm"}, 150.0),
    ({"value": 150.0, "unit": "furlong"}, None),   # refuse rather than assume mm
    ({"value": None, "unit": "mm"}, None),
    ({}, None),
])
def test_measured_mm_conversion(measurement, expected):
    assert G._measured_mm(measurement) == expected


def test_unknown_unit_is_refused_not_assumed():
    """Assuming millimetres for an unrecognised unit is a silent 1000x error
    that still yields a confident-looking FAIL."""
    assert G._measured_mm({"value": 1.5, "unit": "??"}) is None
