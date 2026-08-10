"""Metric scale refinement from a reference object of known size.

Monocular metric depth is impressive but not exact: Metric3D's absolute scale
is inferred from the focal length, so any focal error becomes a proportional
depth error, and the network itself carries a few percent of bias on unseen
cameras. When the user can place an object of known dimension in the scene
(a credit card, an A4 sheet, a printed ruler), we can measure that bias
directly and cancel it.

The correction is a single multiplicative factor ``s`` applied to depth:
because every length derived from the point cloud is homogeneous of degree one
in depth, scaling depth by ``s`` scales all lengths by ``s``, all areas by
``s^2`` and all volumes by ``s^3``. That is what makes a one-parameter fit
legitimate here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from measurecv.core.exceptions import CalibrationError
from measurecv.core.logging import get_logger
from measurecv.core.types import Measured, MeasurementMethod, Unit

log = get_logger(__name__)

__all__ = ["ScaleCorrection", "estimate_scale_correction", "known_reference_sizes"]


#: Common reference objects, longest dimension in metres.
_REFERENCES: dict[str, float] = {
    "credit_card_long": 0.08560,  # ISO/IEC 7810 ID-1
    "credit_card_short": 0.05398,
    "a4_long": 0.297,
    "a4_short": 0.210,
    "letter_long": 0.2794,
    "letter_short": 0.2159,
    "us_quarter": 0.02426,
    "euro_1_coin": 0.02325,
    "aruco_50mm": 0.050,
}


def known_reference_sizes() -> dict[str, float]:
    """Catalogue of built-in reference dimensions, in metres."""
    return dict(_REFERENCES)


@dataclass(frozen=True, slots=True)
class ScaleCorrection:
    """A multiplicative depth-scale correction with its uncertainty."""

    factor: float
    sigma: float
    n_observations: int
    residual_rms: float = 0.0
    reference: str = "custom"

    def __post_init__(self) -> None:
        if not 0.2 < self.factor < 5.0:
            raise CalibrationError(
                f"scale correction {self.factor:.3f} is implausible; this usually means the "
                "reference object was mis-measured or the wrong dimension was matched",
                factor=self.factor,
            )

    def apply_length(self, m: Measured) -> Measured:
        """Scale a length, compounding the correction's own uncertainty."""
        return self._apply(m, power=1)

    def apply_area(self, m: Measured) -> Measured:
        return self._apply(m, power=2)

    def apply_volume(self, m: Measured) -> Measured:
        return self._apply(m, power=3)

    def _apply(self, m: Measured, power: int) -> Measured:
        k = self.factor**power
        value = m.value * k
        # d(s^p)/s^p = p * ds/s  -> relative errors add in quadrature.
        rel = math.hypot(m.relative_error, power * self.sigma / self.factor)
        sigma = abs(value) * rel if math.isfinite(rel) else m.sigma * k
        return Measured(value, sigma, m.unit, m.method, m.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": round(self.factor, 5),
            "sigma": round(self.sigma, 5),
            "n_observations": self.n_observations,
            "residual_rms": round(self.residual_rms, 5),
            "reference": self.reference,
        }


def estimate_scale_correction(
    measured: list[float],
    truth: list[float],
    *,
    reference: str = "custom",
    max_deviation: float = 0.35,
) -> ScaleCorrection:
    """Fit a single scale factor from paired (measured, true) lengths.

    The estimator is the ratio that minimises squared *relative* residuals,
    ``s = sum(m_i t_i) / sum(m_i^2)`` -- equivalently a least-squares fit of
    ``t ~ s * m`` through the origin. Relative weighting matters because
    reference objects of very different sizes should contribute equally.

    Observations deviating more than ``max_deviation`` from the consensus ratio
    are discarded once, which removes a mis-identified reference without
    needing a full RANSAC for what is a one-parameter fit.

    Raises:
        CalibrationError: On empty/invalid input or if everything is rejected.
    """
    if len(measured) != len(truth):
        raise CalibrationError("measured and truth must have equal length")
    if not measured:
        raise CalibrationError("at least one reference observation is required")

    m = np.asarray(measured, dtype=np.float64)
    t = np.asarray(truth, dtype=np.float64)
    if np.any(m <= 0) or np.any(t <= 0):
        raise CalibrationError("reference lengths must be positive")

    ratios = t / m
    consensus = float(np.median(ratios))
    keep = np.abs(ratios / consensus - 1.0) <= max_deviation
    if not keep.any():
        raise CalibrationError(
            "all reference observations rejected as outliers", ratios=ratios.tolist()
        )
    if (~keep).any():
        log.warning("scale_outliers_rejected", rejected=int((~keep).sum()), total=len(m))

    m, t = m[keep], t[keep]
    factor = float(np.sum(m * t) / np.sum(m * m))

    n = int(m.size)
    residuals = t - factor * m
    residual_rms = float(np.sqrt(np.mean(residuals**2)))
    if n > 1:
        # Standard error of the slope for a through-origin fit.
        sigma = float(np.sqrt(np.sum(residuals**2) / (n - 1) / np.sum(m * m)))
    else:
        # A single observation gives no statistical spread; fall back to an
        # assumed 3% uncertainty on locating the reference's extent.
        sigma = 0.03 * factor

    log.info(
        "scale_correction_estimated",
        factor=round(factor, 4),
        sigma=round(sigma, 4),
        n=n,
        reference=reference,
    )
    return ScaleCorrection(
        factor=factor,
        sigma=sigma,
        n_observations=n,
        residual_rms=residual_rms,
        reference=reference,
    )


def scale_from_reference_dimension(measured_length_m: float, reference: str) -> ScaleCorrection:
    """One-shot correction against a named reference from the catalogue."""
    if reference not in _REFERENCES:
        raise CalibrationError(f"unknown reference '{reference}'", available=sorted(_REFERENCES))
    return estimate_scale_correction(
        [measured_length_m], [_REFERENCES[reference]], reference=reference
    )


def as_measured(correction: ScaleCorrection) -> Measured:
    """Expose the correction itself as a reportable quantity."""
    return Measured(
        correction.factor,
        correction.sigma,
        Unit.DIMENSIONLESS,
        MeasurementMethod.REFERENCE_SCALE,
        confidence=min(1.0, correction.n_observations / 3.0),
    )
