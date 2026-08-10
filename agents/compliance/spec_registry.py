"""
Project specification registry — the stored specs Agent 3 validates against.

Before this existed, every caller of ComplianceEngine.validate() had to supply
the Specification inline. That works for an API where an engineer types the
tolerance in, but it means an automated pipeline has nothing to compare against
unless it invents a tolerance -- and an invented tolerance produces a
real-looking PASS/FAIL on nothing at all.

So resolution is explicit and ordered, and the last rung is a refusal:

  1. a spec passed in by the caller            -> source "request"
  2. a matching entry in data/specs.json       -> source "registry"
  3. nothing matches                           -> None, and Agent 3 reports
                                                  status "no_spec"

There is deliberately no default tolerance. A spec registry that guesses is
worse than one that is empty, because the guess is invisible downstream.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = Path(os.getenv("SPEC_REGISTRY_PATH") or (REPO_ROOT / "data" / "specs.json"))

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "specs": []}


@dataclass
class ResolvedSpec:
    spec_id: str
    parameter: str
    expected_value: float
    tolerance_min: float
    tolerance_max: float
    unit: str
    standard_ref: str
    description: str = ""
    source: str = "registry"

    def as_dict(self) -> dict:
        return asdict(self)


def _load() -> list[dict]:
    """Read the registry, reloading when the file changes on disk.

    Hot reload is intentional: an engineer correcting a tolerance mid-demo
    should not have to restart the API to make Agent 3 see it.
    """
    with _lock:
        try:
            mtime = SPEC_FILE.stat().st_mtime
        except OSError:
            _cache["mtime"], _cache["specs"] = None, []
            return []

        if _cache["mtime"] == mtime:
            return _cache["specs"]

        try:
            with open(SPEC_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            specs = data.get("specs", []) if isinstance(data, dict) else []
        except (json.JSONDecodeError, OSError) as e:
            # A malformed registry must not silently behave like an empty one --
            # "no spec found" and "your spec file has a typo" need different fixes.
            print(f"[SpecRegistry] cannot read {SPEC_FILE}: {e}")
            specs = []

        _cache["mtime"], _cache["specs"] = mtime, specs
        return specs


def _matches(entry: dict, parameter: str, zone_id: str, asset_type: str) -> int:
    """Return a match score, or -1 for no match. Higher is more specific.

    `asset_type` is a hint, not a classification -- the caller frequently cannot
    tell rebar from conduit from a spacing measurement alone. An unknown hint
    therefore does not veto a match; it only stops the entry from earning the
    specificity bonus. Treating unknown as "no match" was wrong in the way that
    matters: it made every automated run report "no spec on file" while a
    perfectly good spec sat in the registry.
    """
    if (entry.get("parameter") or "").lower() != parameter.lower():
        return -1

    applies = entry.get("applies_to") or {}
    zones = [str(z).lower() for z in applies.get("zone_ids", ["*"])]
    types = [str(t).lower() for t in applies.get("asset_types", ["*"])]

    zone_hit = (zone_id or "").lower() in zones
    if not zone_hit and "*" not in zones:
        return -1

    hint = (asset_type or "").strip().lower()
    type_wildcard = "*" in types
    type_hit = type_wildcard or (bool(hint) and any(t in hint or hint in t for t in types))

    # A hint that is present and contradicts a type-specific entry is a real
    # mismatch; an absent hint is merely uninformative.
    if hint and not type_hit:
        return -1

    return (2 if zone_hit else 0) + (1 if type_hit and not type_wildcard else 0)


def resolve(parameter: str,
            zone_id: str = "",
            asset_type: str = "",
            override: Optional[dict] = None) -> Optional[ResolvedSpec]:
    """Resolve the governing spec, or None if the project has not defined one."""
    if override:
        try:
            return ResolvedSpec(
                spec_id=override.get("spec_id", "REQUEST-SPEC"),
                parameter=override.get("parameter", parameter),
                expected_value=float(override["expected_value"]),
                tolerance_min=float(override["tolerance_min"]),
                tolerance_max=float(override["tolerance_max"]),
                unit=override.get("unit", "mm"),
                standard_ref=override.get("standard_ref", "supplied with request"),
                description=override.get("description", ""),
                source="request",
            )
        except (KeyError, TypeError, ValueError) as e:
            print(f"[SpecRegistry] ignoring malformed spec override: {e}")

    best, best_score = None, -1
    for entry in _load():
        score = _matches(entry, parameter, zone_id, asset_type)
        if score > best_score:
            best, best_score = entry, score

    if best is None:
        return None

    try:
        return ResolvedSpec(
            spec_id=best["spec_id"],
            parameter=best["parameter"],
            expected_value=float(best["expected_value"]),
            tolerance_min=float(best["tolerance_min"]),
            tolerance_max=float(best["tolerance_max"]),
            unit=best.get("unit", "mm"),
            standard_ref=best.get("standard_ref", "unspecified"),
            description=best.get("description", ""),
            source="registry",
        )
    except (KeyError, TypeError, ValueError) as e:
        print(f"[SpecRegistry] entry {best.get('spec_id')!r} is malformed: {e}")
        return None


def all_specs() -> list[dict]:
    """Every registered spec — used by the API so the UI can show what is stored."""
    return list(_load())


def registry_status() -> dict:
    specs = _load()
    return {
        "path": str(SPEC_FILE),
        "exists": SPEC_FILE.exists(),
        "count": len(specs),
        "spec_ids": [s.get("spec_id") for s in specs],
    }
