"""
BLE indoor localization — RSSI signal model.

GPS is unusable indoors and on a concrete-and-steel site, so zone identity comes
from Bluetooth Low Energy beacons fixed to columns. This module turns raw radio
signal strength into a distance estimate, and a set of distance estimates into a
position.

The physics, briefly. A BLE advertisement's received power falls off with
distance following the log-distance path loss model:

    RSSI(d) = TxPower - 10 * n * log10(d / d0)

where TxPower is the calibrated RSSI at the reference distance d0 (1 m by
convention) and n is the path loss exponent — how fast signal decays in this
particular environment. Free space is n = 2.0. A construction site is not free
space: concrete cores, steel decking and moving plant absorb and reflect, so
n = 2.7-3.5 is realistic indoors. Solving for d:

    d = d0 * 10 ** ((TxPower - RSSI) / (10 * n))

Two properties of this that matter more than the formula:

1. It is exponential, so RSSI error blows up with distance. A ±4 dBm fluctuation
   (entirely normal, a human body between beacon and phone costs more than that)
   is ~30% distance error at n=2.8. Never treat a single reading as truth.
2. It is monotonic but not linear, so the NEAREST beacon is far more reliable
   than the absolute distance to a far one. Ranking beats ranging.

Hence the design below: exponential smoothing per beacon to damp fast fading,
least-squares multilateration when enough beacons are visible, and an explicit
confidence that degrades honestly when they are not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# Environment defaults. Override per-site: measure by placing a phone at a known
# distance and reading RSSI, then solve for n.
DEFAULT_PATH_LOSS_EXPONENT = 2.8      # indoor construction, partially obstructed
DEFAULT_TX_POWER_DBM = -59.0          # typical calibrated RSSI at 1 m for BLE beacons
REFERENCE_DISTANCE_M = 1.0

# Readings weaker than this carry so little information that including them
# degrades a fix rather than improving it.
MIN_USABLE_RSSI = -100.0


@dataclass
class BeaconObservation:
    """One beacon as seen by the phone in a single scan window."""
    beacon_id: str
    rssi: float
    tx_power: Optional[float] = None
    # Populated from the registry during resolution, not by the phone.
    x: Optional[float] = None
    y: Optional[float] = None
    floor: Optional[int] = None
    zone_code: Optional[str] = None

    def distance_m(self, path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT) -> float:
        return rssi_to_distance(self.rssi, self.tx_power or DEFAULT_TX_POWER_DBM,
                                path_loss_exponent)


def rssi_to_distance(rssi: float,
                     tx_power: float = DEFAULT_TX_POWER_DBM,
                     path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT) -> float:
    """Log-distance path loss inverse. Returns metres, clamped to a sane range.

    Clamping matters: a reading stronger than TxPower (phone touching the
    beacon, or a mis-calibrated TxPower) would otherwise yield a sub-centimetre
    distance and dominate the least-squares fit entirely.
    """
    if path_loss_exponent <= 0:
        path_loss_exponent = DEFAULT_PATH_LOSS_EXPONENT
    exponent = (tx_power - rssi) / (10.0 * path_loss_exponent)
    d = REFERENCE_DISTANCE_M * (10.0 ** exponent)
    return max(0.1, min(d, 100.0))


def distance_to_rssi(distance_m: float,
                     tx_power: float = DEFAULT_TX_POWER_DBM,
                     path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT) -> float:
    """Forward model — used by the simulator and by the round-trip tests."""
    d = max(distance_m, 0.01)
    return tx_power - 10.0 * path_loss_exponent * math.log10(d / REFERENCE_DISTANCE_M)


# ---------------------------------------------------------------------------
# Temporal smoothing
# ---------------------------------------------------------------------------

class RssiSmoother:
    """Per-beacon exponential moving average.

    BLE RSSI fast-fades several dBm between consecutive advertisements even from
    a stationary phone — multipath, body blocking, antenna orientation. Feeding
    raw readings into a position solver makes the fix jitter by metres, which on
    this system means a worker's zone flickering between two blueprints.

    alpha is the weight on the newest reading. Lower = smoother but slower to
    follow a worker actually walking. 0.35 settles within ~5 scans (about 5 s at
    1 Hz) while removing most of the fast fading.
    """

    def __init__(self, alpha: float = 0.35):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self._state: dict[str, float] = {}

    def update(self, beacon_id: str, rssi: float) -> float:
        prev = self._state.get(beacon_id)
        smoothed = rssi if prev is None else self.alpha * rssi + (1 - self.alpha) * prev
        self._state[beacon_id] = smoothed
        return smoothed

    def smooth_all(self, observations: list[BeaconObservation]) -> list[BeaconObservation]:
        for o in observations:
            o.rssi = self.update(o.beacon_id, o.rssi)
        return observations

    def forget(self, beacon_id: str) -> None:
        self._state.pop(beacon_id, None)

    def reset(self) -> None:
        self._state.clear()


# ---------------------------------------------------------------------------
# Position solving
# ---------------------------------------------------------------------------

@dataclass
class PositionFix:
    x: Optional[float]
    y: Optional[float]
    floor: Optional[int]
    zone_code: Optional[str]
    method: str                     # 'multilateration' | 'nearest_beacon' | 'none'
    confidence: float               # 0..1
    accuracy_m: Optional[float]     # estimated 1-sigma radius, None if unknown
    beacons_used: int
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "x": round(self.x, 3) if self.x is not None else None,
            "y": round(self.y, 3) if self.y is not None else None,
            "floor": self.floor,
            "zone_code": self.zone_code,
            "method": self.method,
            "confidence": round(self.confidence, 3),
            "accuracy_m": round(self.accuracy_m, 2) if self.accuracy_m is not None else None,
            "beacons_used": self.beacons_used,
            **self.detail,
        }


def _usable(observations: list[BeaconObservation]) -> list[BeaconObservation]:
    return [o for o in observations
            if o.rssi is not None and o.rssi >= MIN_USABLE_RSSI
            and o.x is not None and o.y is not None]


def nearest_beacon_fix(observations: list[BeaconObservation]) -> PositionFix:
    """Strongest-signal fix. Used with fewer than three beacons.

    Deliberately reports the beacon's OWN coordinates rather than trying to
    offset by the estimated distance: with one beacon the direction is entirely
    unknown, so any offset would be invention. The estimated distance goes into
    accuracy_m instead, which is what it actually represents.
    """
    usable = _usable(observations)
    if not usable:
        return PositionFix(None, None, None, None, "none", 0.0, None, 0,
                           {"reason": "no beacons with a known position were seen"})

    best = max(usable, key=lambda o: o.rssi)
    d = best.distance_m()

    # Confidence from proximity: standing under a beacon is a reliable zone
    # assignment; 15 m away through a wall is not.
    if d <= 2.0:
        conf = 0.88
    elif d <= 5.0:
        conf = 0.74
    elif d <= 10.0:
        conf = 0.55
    else:
        conf = 0.35

    return PositionFix(
        x=best.x, y=best.y, floor=best.floor, zone_code=best.zone_code,
        method="nearest_beacon", confidence=conf, accuracy_m=d,
        beacons_used=len(usable),
        detail={"nearest_beacon_id": best.beacon_id,
                "nearest_rssi": round(best.rssi, 1),
                "estimated_range_m": round(d, 2),
                "note": "fewer than 3 beacons visible — zone from the strongest "
                        "beacon; position is that beacon's own location, not a "
                        "solved fix"},
    )


def multilaterate(observations: list[BeaconObservation],
                  path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT,
                  iterations: int = 40) -> PositionFix:
    """Weighted least-squares position from three or more ranged beacons.

    Solved by Gauss-Newton on the range residuals rather than the linearised
    circle-intersection form, because the linear form is badly conditioned when
    beacons are nearly collinear — which is exactly how beacons on a corridor
    wall end up.

    Weighting is 1/d^2: near beacons have far smaller absolute range error (see
    the module docstring), so they should dominate. Without weighting a distant
    beacon's ±10 m error drags the fix across the room.
    """
    usable = _usable(observations)
    if len(usable) < 3:
        return nearest_beacon_fix(observations)

    ranges = [o.distance_m(path_loss_exponent) for o in usable]
    weights = [1.0 / max(r * r, 0.25) for r in ranges]

    # Initial guess: weighted centroid. Starting at the strongest beacon instead
    # biases the solver toward it and can stall on a local minimum.
    wsum = sum(weights)
    x = sum(w * o.x for w, o in zip(weights, usable)) / wsum
    y = sum(w * o.y for w, o in zip(weights, usable)) / wsum

    for _ in range(iterations):
        # Normal equations for the Gauss-Newton step, accumulated directly —
        # a 2x2 system needs no matrix library.
        a11 = a12 = a22 = b1 = b2 = 0.0
        for w, o, r in zip(weights, usable, ranges):
            dx, dy = x - o.x, y - o.y
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                continue
            residual = dist - r
            jx, jy = dx / dist, dy / dist       # d(dist)/dx, d(dist)/dy
            a11 += w * jx * jx
            a12 += w * jx * jy
            a22 += w * jy * jy
            b1 -= w * jx * residual
            b2 -= w * jy * residual

        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-12:
            break                               # degenerate geometry (collinear)
        step_x = (b1 * a22 - b2 * a12) / det
        step_y = (b2 * a11 - b1 * a12) / det
        x += step_x
        y += step_y
        if math.hypot(step_x, step_y) < 1e-4:
            break

    # Residual RMS is the honest accuracy estimate: how far the solved point is
    # from being consistent with the ranges it was solved from.
    resid = [math.hypot(x - o.x, y - o.y) - r for o, r in zip(usable, ranges)]
    rms = math.sqrt(sum(e * e for e in resid) / len(resid))

    # Confidence falls as the fit worsens and rises with beacon count. An RMS of
    # 2 m on a site with 5 m zone granularity is still a usable zone assignment.
    conf = 0.92
    conf *= max(0.25, 1.0 - min(rms / 8.0, 0.7))
    if len(usable) >= 4:
        conf = min(conf * 1.05, 0.95)

    # Zone: the nearest beacon TO THE SOLVED POINT, not the strongest signal.
    # These differ when the worker stands between two beacons and a reflection
    # briefly makes the farther one stronger.
    nearest = min(usable, key=lambda o: math.hypot(x - o.x, y - o.y))
    floors = [o.floor for o in usable if o.floor is not None]

    return PositionFix(
        x=x, y=y,
        floor=max(set(floors), key=floors.count) if floors else None,
        zone_code=nearest.zone_code,
        method="multilateration",
        confidence=round(max(0.0, min(conf, 0.95)), 3),
        accuracy_m=rms,
        beacons_used=len(usable),
        detail={"residual_rms_m": round(rms, 3),
                "ranges_m": {o.beacon_id: round(r, 2) for o, r in zip(usable, ranges)},
                "zone_from_beacon": nearest.beacon_id},
    )


def resolve_position(observations: list[BeaconObservation],
                     path_loss_exponent: float = DEFAULT_PATH_LOSS_EXPONENT) -> PositionFix:
    """Entry point: pick the best available method for what was actually seen."""
    usable = _usable(observations)
    if len(usable) >= 3:
        return multilaterate(usable, path_loss_exponent)
    return nearest_beacon_fix(observations)
