"""Metric geometry: back-projection, filtering, plane fitting, boxes, hulls, errors."""

from measurecv.geometry.backproject import (
    FilterReport,
    backproject_depth_map,
    backproject_mask,
    depth_edge_mask,
    largest_component,
    robust_depth_gate,
    statistical_outlier_filter,
)
from measurecv.geometry.hull import (
    closed_hull_volume,
    convex_hull,
    ellipsoid_volume,
    hull_metrics,
    mirrored_hull_volume,
)
from measurecv.geometry.obb import (
    OrientedBox,
    RectFit,
    fit_ground_aligned_box,
    fit_pca_box,
    min_area_rect,
    principal_axes,
    trimmed_extent,
)
from measurecv.geometry.plane import (
    SupportFrame,
    estimate_support_plane,
    fit_plane_lsq,
    fit_plane_ransac,
)
from measurecv.geometry.uncertainty import (
    ErrorBudget,
    combine_relative,
    effective_sample_size,
    extent_uncertainty,
    monte_carlo_extents,
    product_uncertainty,
    scalar_from_samples,
)

__all__ = [
    "ErrorBudget",
    "FilterReport",
    "OrientedBox",
    "RectFit",
    "SupportFrame",
    "backproject_depth_map",
    "backproject_mask",
    "closed_hull_volume",
    "combine_relative",
    "convex_hull",
    "depth_edge_mask",
    "effective_sample_size",
    "ellipsoid_volume",
    "estimate_support_plane",
    "extent_uncertainty",
    "fit_ground_aligned_box",
    "fit_pca_box",
    "fit_plane_lsq",
    "fit_plane_ransac",
    "hull_metrics",
    "largest_component",
    "min_area_rect",
    "mirrored_hull_volume",
    "monte_carlo_extents",
    "principal_axes",
    "product_uncertainty",
    "robust_depth_gate",
    "scalar_from_samples",
    "statistical_outlier_filter",
    "trimmed_extent",
]
