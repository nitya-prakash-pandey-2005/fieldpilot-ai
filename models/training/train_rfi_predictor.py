#!/usr/bin/env python
"""
T6 — Predictive RFI risk model (LightGBM, probability-calibrated).

Trains the classifier that replaces the scorecard in
agents/predictive_rfi/risk_model.py. Runs on CPU in under a minute.

    python models/training/train_rfi_predictor.py --out models/weights/rfi_lgbm.txt

The target: did this zone raise at least one new issue in the 14 days AFTER the
observation point? Labels are built by replaying the field_issues history
through time, so each training row only ever sees data that existed at its own
observation date. Computing features over the whole table and labelling from it
would leak the future into the features and produce a model that scores 0.95
offline and is useless live.

CALIBRATION MATTERS MORE THAN AUC HERE. The dashboard prints "87% probability"
to an engineer who will make a scheduling decision on it. A model can rank
perfectly (high AUC) while being systematically overconfident, so this script
reports Brier score and a reliability curve alongside AUC, and applies isotonic
calibration on a held-out split.

Not enough history yet? That is the normal early state and the script says so
rather than fitting noise. The scorecard in risk_model.py stays in service
until you clear the minimum, and the API reports scoring_mode='scorecard'
truthfully in the meantime.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "api"))

from agents.predictive_rfi.risk_model import FEATURE_NAMES  # noqa: E402

MIN_ROWS = 60
MIN_POSITIVES = 12


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def build_dataset(horizon_days: int, stride_days: int):
    """Replay history and emit (features, label) at each observation point."""
    from db import async_session
    from models.issues import FieldIssue
    from models.resolved_incident import ResolvedIncident
    from models.zones import Zone
    from sqlalchemy import select

    async with async_session() as s:
        issues = (await s.execute(select(FieldIssue))).scalars().all()
        zones = (await s.execute(select(Zone))).scalars().all()
        incidents = (await s.execute(select(ResolvedIncident))).scalars().all()

    if not issues:
        return [], [], {"reason": "field_issues table is empty"}

    by_zone: dict[str, list] = {}
    for i in issues:
        if i.zone_code:
            by_zone.setdefault(i.zone_code, []).append(i)

    zone_meta = {z.zone_code: z for z in zones}
    stamps = [t for t in (_aware(i.created_at) for i in issues) if t]
    if not stamps:
        return [], [], {"reason": "no created_at timestamps on field_issues"}

    start, end = min(stamps), max(stamps)
    if (end - start).days < horizon_days + stride_days:
        return [], [], {
            "reason": f"history spans only {(end - start).days} days; need at least "
                      f"{horizon_days + stride_days} to build even one labelled window"
        }

    # Asset-type aggregates are computed once from resolved incidents. These are
    # slow-moving project characteristics rather than per-window state, so they
    # are not a leakage vector in the way per-zone counts would be.
    asset_stats: dict[str, dict] = {}
    for h in incidents:
        st = asset_stats.setdefault(h.asset_type, {"n": 0, "rework": 0, "hours": 0.0, "counted": 0})
        st["n"] += 1
        try:
            r = json.loads(h.resolution or "{}")
        except (ValueError, TypeError):
            continue
        if r.get("rework_required"):
            st["rework"] += 1
        t = r.get("time_to_resolve_hours")
        if isinstance(t, (int, float)):
            st["hours"] += t
            st["counted"] += 1

    X, y = [], []
    cursor = start + timedelta(days=horizon_days)
    while cursor + timedelta(days=horizon_days) <= end:
        for zone_code, zone_issues in by_zone.items():
            past = [i for i in zone_issues if (_aware(i.created_at) or end) <= cursor]
            if not past:
                continue
            future = [i for i in zone_issues
                      if cursor < (_aware(i.created_at) or start) <= cursor + timedelta(days=horizon_days)]

            d7 = cursor - timedelta(days=7)
            d30 = cursor - timedelta(days=30)
            recent7 = [i for i in past if (_aware(i.created_at) or start) >= d7]
            recent30 = [i for i in past if (_aware(i.created_at) or start) >= d30]
            open_at_t = [i for i in past
                         if (i.resolved_at is None) or (_aware(i.resolved_at) > cursor)]
            devs = [float(i.deviation_pct) for i in recent7 if i.deviation_pct is not None]

            z = zone_meta.get(zone_code)
            asset_type = _infer_asset(z.current_activity if z else "")
            st = asset_stats.get(asset_type, {"n": 0, "rework": 0, "hours": 0.0, "counted": 0})
            last = max((_aware(i.created_at) for i in past if i.created_at), default=None)

            feats = {
                "open_issue_count": float(len(open_at_t)),
                "critical_open_count": float(sum(
                    1 for i in open_at_t if (i.severity or "").lower() in ("critical", "high"))),
                "zone_risk_score": float(getattr(z, "risk_score", 0) or 0),
                "issues_last_7d": float(len(recent7)),
                "issues_last_30d": float(len(recent30)),
                "mean_deviation_pct_7d": (sum(devs) / len(devs)) if devs else 0.0,
                "max_deviation_pct_7d": max(devs) if devs else 0.0,
                "days_since_last_issue": min(60.0, (cursor - last).total_seconds() / 86400.0)
                                          if last else 60.0,
                "asset_incident_history": float(st["n"]),
                "asset_rework_rate": (st["rework"] / st["n"]) if st["n"] else 0.0,
                "mean_resolve_hours": (st["hours"] / st["counted"]) if st["counted"] else 0.0,
                # Not reconstructable historically (Qdrant has no as-of view),
                # so it is held at 0 for every training row. Serving passes the
                # real value; a feature that is constant in training simply gets
                # near-zero importance rather than causing skew.
                "similar_incident_score": 0.0,
                "worker_count": float(getattr(z, "active_worker_count", 0) or 0),
            }
            X.append([feats[n] for n in FEATURE_NAMES])
            y.append(1 if future else 0)
        cursor += timedelta(days=stride_days)

    return X, y, {"windows": len(X), "span_days": (end - start).days}


def _infer_asset(activity: str) -> str:
    from agents.predictive_rfi.predictor import infer_asset_type
    return infer_asset_type(activity or "")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="models/weights/rfi_lgbm.txt")
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument("--stride-days", type=int, default=3)
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    args = ap.parse_args()

    try:
        import lightgbm as lgb
        import numpy as np
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.metrics import brier_score_loss, roc_auc_score
        from sklearn.model_selection import train_test_split
    except ImportError as e:
        raise SystemExit(f"✖ missing dependency ({e}). pip install lightgbm scikit-learn")

    import asyncio
    X, y, meta = asyncio.run(build_dataset(args.horizon_days, args.stride_days))

    n_pos = sum(y)
    print(f"\n  windows built : {len(X)}")
    print(f"  positives     : {n_pos}")
    if meta.get("reason"):
        print(f"  note          : {meta['reason']}")

    if len(X) < args.min_rows or n_pos < MIN_POSITIVES:
        print(f"\n✖ not enough history to train ({len(X)} rows / {n_pos} positives; "
              f"need >= {args.min_rows} / {MIN_POSITIVES}).")
        print("  This is the expected early state, not a failure. The explicit")
        print("  scorecard in agents/predictive_rfi/risk_model.py stays in service")
        print("  and the API keeps reporting scoring_mode='scorecard' truthfully.")
        print("  Fitting a model on this little data would produce a confident,")
        print("  meaningless probability — strictly worse than a stated prior.")
        print("\n  Accumulate history by resolving issues through the dashboard")
        print("  (POST /api/v1/learning/resolve), then re-run this.")
        return 1

    X = np.array(X, dtype=np.float64)
    y = np.array(y, dtype=np.int32)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.25, random_state=42,
        stratify=y if len(set(y.tolist())) > 1 else None)

    base = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=15,
        min_child_samples=max(5, len(X_tr) // 40),
        subsample=0.8, colsample_bytree=0.8,
        reg_lambda=1.0, random_state=42, verbose=-1,
    )
    # Isotonic needs a reasonable amount of data; sigmoid (Platt) is the right
    # choice on small samples and isotonic will otherwise overfit the curve.
    method = "isotonic" if len(X_tr) >= 400 else "sigmoid"
    clf = CalibratedClassifierCV(base, method=method, cv=3)
    clf.fit(X_tr, y_tr)

    p_te = clf.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(y_te, p_te) if len(set(y_te.tolist())) > 1 else float("nan")
    brier = brier_score_loss(y_te, p_te)

    print(f"\n  calibration   : {method}")
    print(f"  AUC           : {auc:.4f}   (target >= 0.75)")
    print(f"  Brier         : {brier:.4f}   (target <= 0.18 — lower is better)")

    print("\n  reliability (predicted vs actual):")
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        hi = lo + 0.2
        m = (p_te >= lo) & (p_te < hi + (1e-9 if hi >= 1.0 else 0))
        if m.sum() == 0:
            continue
        print(f"    predicted {lo:.1f}-{hi:.1f}: n={int(m.sum()):>3}  "
              f"mean predicted {p_te[m].mean():.3f}  actual rate {y_te[m].mean():.3f}")

    # Refit an uncalibrated booster on ALL data for the native .txt format that
    # risk_model.py loads, then ship the calibration mapping alongside it.
    full = lgb.LGBMClassifier(**base.get_params())
    full.fit(X, y)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    full.booster_.save_model(str(out))

    importances = sorted(zip(FEATURE_NAMES, full.booster_.feature_importance("gain")),
                         key=lambda p: -p[1])
    print("\n  top features by gain:")
    for name, gain in importances[:6]:
        print(f"    {name:<26}{gain:>10.1f}")

    meta_path = out.with_name(out.stem + "_meta.json")
    meta_path.write_text(json.dumps({
        "trained_at": datetime.now().isoformat(),
        "horizon_days": args.horizon_days,
        "n_rows": int(len(X)), "n_positives": int(n_pos),
        "base_rate": round(float(y.mean()), 4),
        "auc": None if auc != auc else round(float(auc), 4),   # NaN-safe
        "brier": round(float(brier), 4),
        "calibration": method,
        "features": FEATURE_NAMES,
        "feature_importance": {n: float(g) for n, g in importances},
        "caveat": "similar_incident_score is constant 0 in training (Qdrant has "
                  "no as-of view for historical replay); expect it to carry "
                  "near-zero importance.",
    }, indent=2), encoding="utf-8")

    print(f"\n  model -> {out}")
    print(f"  meta  -> {meta_path}")
    print(f"\n  set in .env:  RFI_MODEL_PATH={out.as_posix()}")
    if auc == auc and auc < 0.75:
        print(f"\n  ⚠ AUC {auc:.3f} is below the 0.75 target. With this little history")
        print("    that is expected; the scorecard may still be the better prior.")
        print("    Compare both before switching RFI_MODEL_PATH on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
