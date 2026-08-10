"""Error propagation for monocular metric measurement.

A measurement without an error bar is an opinion. This module turns the known
error sources into a defensible 1-sigma estimate on every reported quantity.

The error budget
----------------
Back-projection is ``X = (u - cx) Z / f``, ``Y = (v - cy) Z / f``, ``Z = Z``.
Differentiating gives four distinct contributions, which behave differently and
must not be lumped together:

============================  =====================================  ==========
Source                        Affects                                Character
============================  =====================================  ==========
Metric scale bias (depth)     all three axes, multiplicatively        systematic
Focal-length error            lateral (X, Y) only                     systematic
Per-pixel depth noise         mainly the axial (Z) extent             random
Mask/edge localisation        lateral extents                         random
============================  =====================================  ==========

Systematic terms do **not** shrink with more pixels -- averaging a million
pixels does not fix a 5% scale bias -- so they set the accuracy floor. Random
terms shrink with sample count, but only as ``n_eff``, which we deliberately
take as ``sqrt(n)`` rather than ``n``: monocular depth error is strongly
spatially correlated, and treating neighbouring pixels as independent samples
would understate the uncertainty by an order of magnitude.

This is first-order (linear) propagation. It is exact for the lateral
relations, which are genuinely linear, and a good approximation for extents.
For the nonlinear fits (convex hull, minimum-area rectangle) set
``measurement.monte_carlo_samples`` to switch to sampling, which captures the
fit's own nonlinearity at a real compute cost.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from measurecv.core.types import Measured, MeasurementMethod, Unit

__all__ = [
    "ErrorBudget",
    "combine_relative",
    "effective_sample_size",
    "extent_uncertainty",
    "monte_carlo_extents",
    "product_uncertainty",
    "scalar_from_samples",
]


@dataclass(frozen=True, slots=True)
class ErrorBudget:
    """The error sources active for one frame."""

    depth_scale_sigma: float = 0.05
    """Relative 1-sigma on the global metric scale (systematic)."""

    depth_noise_sigma: float = 0.02
    """Relative 1-sigma of per-pixel depth noise (random)."""

    focal_sigma: float = 0.02
    """Relative 1-sigma on the focal length (systematic, lateral only)."""

    pixel_sigma: float = 1.5
    """1-sigma localisation error of a mask boundary, in pixels."""

    def to_dict(self) -> dict[str, float]:
        return {
            "depth_scale_sigma": self.depth_scale_sigma,
            "depth_noise_sigma": self.depth_noise_sigma,
            "focal_sigma": self.focal_sigma,
            "pixel_sigma": self.pixel_sigma,
        }


def combine_relative(*relatives: float) -> float:
    """Quadrature sum of independent relative errors."""
    return math.sqrt(sum(r * r for r in relatives if math.isfinite(r)))


def effective_sample_size(n_points: int) -> float:
    """Independent-sample count implied by ``n_points`` correlated pixels.

    ``sqrt(n)`` is a deliberately conservative choice. Monocular depth errors
    have correlation lengths of tens of pixels, so the naive ``n`` would be
    wildly optimistic; ``sqrt(n)`` reproduces the empirical observation that
    doubling an object's pixel count improves repeatability, but far less than
    the ideal 1/sqrt(2).
    """
    return max(1.0, math.sqrt(max(1, n_points)))


def extent_uncertainty(
    extent: float,
    *,
    depth: float,
    axis: NDArray[np.float64],
    focal_px: float,
    n_points: int,
    budget: ErrorBudget,
    view_direction: NDArray[np.float64] | None = None,
) -> float:
    """1-sigma uncertainty of a single 3-D extent.

    Args:
        extent: The measured length, metres.
        depth: Representative depth of the object, metres.
        axis: Unit vector of the measured direction in camera coordinates.
        focal_px: Focal length in pixels (use the geometric mean of fx, fy).
        n_points: Number of 3-D samples backing the estimate.
        budget: Active error sources.
        view_direction: Optical axis; defaults to +Z.

    Returns:
        Standard uncertainty in metres.

    The axial/lateral split is done by projecting ``axis`` onto the view
    direction: an extent along the line of sight inherits depth *noise*, while
    one perpendicular to it inherits focal and pixel error instead. An object
    measured across the image is meaningfully more accurate than the same
    object measured in depth, and the error bars should show that.
    """
    if extent <= 0 or depth <= 0:
        return 0.0

    view = np.array([0.0, 0.0, 1.0]) if view_direction is None else view_direction
    view = view / np.linalg.norm(view)
    axis_unit = axis / max(np.linalg.norm(axis), 1e-12)

    axial = abs(float(axis_unit @ view))  # component along the ray
    lateral = math.sqrt(max(0.0, 1.0 - axial**2))  # component across the image

    n_eff = effective_sample_size(n_points)

    # -- systematic (do not shrink with n) ---------------------------------
    # Scale bias multiplies every reconstructed coordinate.
    rel_systematic_sq = budget.depth_scale_sigma**2
    # Focal error only distorts the lateral directions.
    rel_systematic_sq += (lateral * budget.focal_sigma) ** 2

    # -- random (shrink with the effective sample size) --------------------
    # Depth noise enters the axial extent as the difference of two noisy
    # endpoint estimates, hence the sqrt(2).
    axial_noise_m = axial * budget.depth_noise_sigma * depth * math.sqrt(2.0) / n_eff
    # Boundary localisation converts to metres through the pinhole relation.
    lateral_pixel_m = (
        lateral * budget.pixel_sigma * math.sqrt(2.0) * depth / focal_px / math.sqrt(n_eff)
    )

    systematic_m = extent * math.sqrt(rel_systematic_sq)
    return math.sqrt(systematic_m**2 + axial_noise_m**2 + lateral_pixel_m**2)


def product_uncertainty(
    values: list[float], sigmas: list[float], *, shared_relative: float = 0.0
) -> tuple[float, float]:
    """Uncertainty of a product of measured quantities (area, volume).

    Args:
        values: The factors.
        sigmas: Their standard uncertainties.
        shared_relative: A relative error common to *all* factors -- typically
            the metric-scale bias. This is the important subtlety: for a volume
            built from three lengths that all ride on the same depth scale, a
            5% scale error is a 15% volume error, not the 8.7% that independent
            quadrature would give. Correlated errors add linearly.

    Returns:
        ``(product, sigma)``.
    """
    if not values:
        return (0.0, 0.0)
    product = float(np.prod(values))
    if product == 0.0:
        return (0.0, 0.0)

    # Independent part: the residual after removing the shared component.
    independent_sq = 0.0
    for value, sigma in zip(values, sigmas, strict=True):
        if value == 0:
            return (0.0, 0.0)
        rel = sigma / abs(value)
        residual_sq = max(0.0, rel * rel - shared_relative * shared_relative)
        independent_sq += residual_sq

    # Correlated part: adds linearly, once per factor.
    correlated = len(values) * shared_relative
    total_rel = math.sqrt(independent_sq + correlated * correlated)
    return (product, abs(product) * total_rel)


def scalar_from_samples(
    samples: NDArray[np.float64],
    unit: Unit,
    method: MeasurementMethod,
    confidence: float = 1.0,
) -> Measured:
    """Summarise Monte Carlo samples into a :class:`Measured`.

    The median is used rather than the mean: the distributions produced by
    extent and hull fits are skewed, and the median is the more faithful point
    estimate. The sigma comes from the 16th-84th percentile half-width, which
    equals the standard deviation for a normal distribution but is robust to
    the heavy tail that a few degenerate resamples can produce.
    """
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return Measured(0.0, 0.0, unit, method, 0.0)
    if finite.size == 1:
        return Measured(float(finite[0]), 0.0, unit, method, confidence)
    p16, p50, p84 = np.percentile(finite, [15.865, 50.0, 84.135])
    return Measured(float(p50), float((p84 - p16) * 0.5), unit, method, confidence)


def monte_carlo_extents(
    points: NDArray[np.float64],
    fit: Callable[[NDArray[np.float64]], NDArray[np.float64]],
    *,
    budget: ErrorBudget,
    focal_px: float,
    n_samples: int = 256,
    seed: int = 0x5EED,
) -> NDArray[np.float64]:
    """Propagate depth/focal noise through an arbitrary fit by sampling.

    Each draw perturbs the cloud with a physically structured noise model --
    one global scale factor (systematic, shared by every point) plus per-point
    depth jitter (random) -- then re-runs ``fit``. This is what captures the
    nonlinearity that first-order propagation misses for hull and rectangle
    fits.

    Args:
        points: ``(N, 3)`` camera-frame cloud.
        fit: Maps a perturbed cloud to a vector of quantities.
        budget: Error sources.
        focal_px: Focal length, used to re-derive lateral coordinates after
            perturbing depth (X and Y are proportional to Z, so they must move
            with it -- perturbing Z alone would be physically wrong).
        n_samples: Number of draws.

    Returns:
        ``(n_samples, k)`` array of fitted quantities.
    """
    rng = np.random.default_rng(seed)
    results: list[NDArray[np.float64]] = []

    z = points[:, 2]
    # Recover the normalised image-plane coordinates so that a perturbed depth
    # regenerates a geometrically consistent X and Y.
    with np.errstate(divide="ignore", invalid="ignore"):
        xn = np.where(z > 1e-9, points[:, 0] / z, 0.0)
        yn = np.where(z > 1e-9, points[:, 1] / z, 0.0)

    for _ in range(n_samples):
        scale = 1.0 + rng.normal(0.0, budget.depth_scale_sigma)
        focal_ratio = 1.0 + rng.normal(0.0, budget.focal_sigma)
        jitter = rng.normal(0.0, budget.depth_noise_sigma, size=z.shape)

        z_s = z * scale * (1.0 + jitter)
        # A focal error rescales the lateral directions only.
        perturbed = np.stack([xn * z_s / focal_ratio, yn * z_s / focal_ratio, z_s], axis=1)
        try:
            results.append(np.asarray(fit(perturbed), dtype=np.float64))
        except Exception:  # a degenerate resample is a legitimate outcome
            continue

    if not results:
        return np.zeros((0, 0))
    return np.stack(results, axis=0)
