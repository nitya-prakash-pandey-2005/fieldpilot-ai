"""
Tests for the project specification registry.

The property under test is a refusal. Agent 3 compares a measurement to a stored
tolerance; if no tolerance is on file and the registry invents a plausible one,
the resulting PASS/FAIL is indistinguishable from a real verdict — same shape,
same confidence, same downstream escalation. So "no spec" must return None and
must keep returning None, in every shape of missing.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents.compliance import spec_registry as SR


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Point the registry at a temp file and clear its mtime cache."""
    def write(specs):
        path = tmp_path / "specs.json"
        path.write_text(json.dumps({"specs": specs}), encoding="utf-8")
        monkeypatch.setattr(SR, "SPEC_FILE", path)
        monkeypatch.setattr(SR, "_cache", {"mtime": None, "specs": []})
        return path
    return write


def _entry(spec_id, zones, types, parameter="spacing", expected=150.0):
    return {
        "spec_id": spec_id, "parameter": parameter,
        "applies_to": {"zone_ids": zones, "asset_types": types},
        "expected_value": expected, "tolerance_min": expected - 10,
        "tolerance_max": expected + 10, "unit": "mm",
        "standard_ref": "TEST-REF",
    }


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------

def test_no_matching_spec_returns_none(registry):
    registry([_entry("S1", ["A12"], ["rebar"])])
    assert SR.resolve("spacing", zone_id="Z99", asset_type="rebar") is None


def test_unknown_parameter_returns_none(registry):
    registry([_entry("S1", ["*"], ["*"])])
    assert SR.resolve("torque", zone_id="A12") is None


def test_empty_registry_returns_none(registry):
    registry([])
    assert SR.resolve("spacing", zone_id="A12") is None


def test_missing_file_returns_none_rather_than_a_default(monkeypatch, tmp_path):
    monkeypatch.setattr(SR, "SPEC_FILE", tmp_path / "does-not-exist.json")
    monkeypatch.setattr(SR, "_cache", {"mtime": None, "specs": []})
    assert SR.resolve("spacing", zone_id="A12") is None


def test_malformed_entry_is_dropped_not_guessed(registry):
    """A spec missing its tolerance must not resolve with a filled-in one."""
    registry([{"spec_id": "BROKEN", "parameter": "spacing",
               "applies_to": {"zone_ids": ["*"], "asset_types": ["*"]},
               "expected_value": 150.0}])            # no tolerance_min/max
    assert SR.resolve("spacing", zone_id="A12") is None


# ---------------------------------------------------------------------------
# Specificity
# ---------------------------------------------------------------------------

def test_zone_specific_spec_beats_project_default(registry):
    registry([
        _entry("DEFAULT", ["*"], ["*"], expected=150.0),
        _entry("ZONE-A12", ["A12"], ["rebar"], expected=200.0),
    ])
    spec = SR.resolve("spacing", zone_id="A12", asset_type="rebar")
    assert spec is not None and spec.spec_id == "ZONE-A12"
    assert spec.expected_value == 200.0


def test_falls_back_to_wildcard_zone(registry):
    registry([
        _entry("DEFAULT", ["*"], ["*"], expected=150.0),
        _entry("ZONE-A12", ["A12"], ["rebar"], expected=200.0),
    ])
    spec = SR.resolve("spacing", zone_id="B7", asset_type="rebar")
    assert spec is not None and spec.spec_id == "DEFAULT"


def test_unknown_asset_hint_still_matches(registry):
    """The caller usually cannot tell rebar from conduit from a spacing value.
    An absent hint is uninformative, not disqualifying — treating it as a
    mismatch made every automated run report 'no spec on file'."""
    registry([_entry("ZONE-A12", ["A12"], ["rebar"])])
    assert SR.resolve("spacing", zone_id="A12", asset_type="") is not None


def test_contradicting_asset_hint_is_a_real_mismatch(registry):
    """A hint that is present and wrong must not silently borrow another
    trade's tolerance."""
    registry([_entry("REBAR-ONLY", ["A12"], ["rebar"])])
    assert SR.resolve("spacing", zone_id="A12", asset_type="ductwork") is None


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

def test_request_override_wins_and_is_labelled(registry):
    registry([_entry("ZONE-A12", ["A12"], ["rebar"], expected=150.0)])
    spec = SR.resolve("spacing", zone_id="A12", asset_type="rebar", override={
        "expected_value": 300.0, "tolerance_min": 295.0, "tolerance_max": 305.0,
    })
    assert spec is not None
    assert spec.expected_value == 300.0
    # Provenance has to travel — a verdict against a caller-supplied tolerance
    # carries different weight than one against the project's own schedule.
    assert spec.source == "request"


def test_malformed_override_falls_back_to_registry(registry):
    registry([_entry("ZONE-A12", ["A12"], ["rebar"], expected=150.0)])
    spec = SR.resolve("spacing", zone_id="A12", asset_type="rebar",
                      override={"expected_value": "not-a-number"})
    assert spec is not None and spec.source == "registry"
    assert spec.expected_value == 150.0


# ---------------------------------------------------------------------------
# The shipped registry
# ---------------------------------------------------------------------------

def test_shipped_registry_parses_and_covers_rebar_spacing():
    """data/specs.json is what Agent 3 actually reads in a demo."""
    status = SR.registry_status()
    assert status["exists"], f"spec registry missing at {status['path']}"
    assert status["count"] >= 1

    spec = SR.resolve("spacing", zone_id="A12", asset_type="rebar")
    assert spec is not None, "the shipped registry cannot resolve rebar spacing in A12"
    assert spec.tolerance_min < spec.expected_value < spec.tolerance_max
    assert spec.standard_ref, "a spec with no standard_ref cannot be cited in an RFI"
