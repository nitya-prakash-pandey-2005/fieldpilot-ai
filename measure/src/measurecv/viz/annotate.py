"""Rendering measurements onto frames.

Visualisation is part of the product, not decoration: an operator glancing at
an annotated frame needs to see not just the number but how much to trust it.
Three design choices follow from that:

* Every dimension is drawn **with its uncertainty** (``0.42 +/- 0.03 m``).
  A bare number invites false precision.
* Label colour encodes confidence, so a low-confidence measurement is visually
  distinct without having to read the text.
* Labels are placed by a simple collision-avoidance pass, because overlapping
  text in a crowded scene is the fastest way to make a correct measurement
  unreadable.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics
from measurecv.core.types import Measured, ObjectMeasurement, SceneMeasurement

__all__ = ["AnnotationStyle", "draw_depth_map", "draw_scene", "label_color", "track_color"]


@dataclass(slots=True)
class AnnotationStyle:
    """Appearance knobs."""

    font: int = cv2.FONT_HERSHEY_SIMPLEX
    font_scale: float = 0.45
    thickness: int = 1
    box_thickness: int = 2
    mask_alpha: float = 0.35
    show_masks: bool = True
    show_dimensions: bool = True
    show_distance: bool = True
    show_volume: bool = False
    show_confidence: bool = True
    show_uncertainty: bool = True
    show_track_id: bool = True
    show_3d_box: bool = True
    box_3d_min_confidence: float = 0.5
    """Only draw the 3-D wireframe above this confidence.

    A projected box is a strong visual assertion: it says the system knows the
    object's pose and extent in space. For a truncated or near-degenerate
    object it does not, and the fitted box sprawls across the frame -- which
    both looks broken and contradicts the low confidence reported right next to
    it. The 2-D box and the numbers still appear; only the claim the engine
    cannot back is withheld."""

    reserved_top_px: int = 0
    """Vertical space to keep clear of labels, for a caller-drawn status strip."""

    min_confidence: float = 0.0
    """Objects below this are drawn dimmed rather than hidden, so an operator
    can see that something was detected but not measured."""

    max_labels: int = 8
    """Cap on how many detail labels are drawn.

    Boxes and masks are always drawn for every object; this limits only the
    text. Past roughly eight labels on a single frame the panels overlap so
    badly that they hide the scene *and* each other, which makes a correct
    measurement unreadable. The largest objects keep their labels, since those
    are the ones a viewer is looking at; the rest are marked with a compact
    index tag and remain available in the JSON."""

    compact_labels: bool | None = None
    """Force single-line labels. ``None`` decides automatically from how
    crowded the frame is."""


#: Perceptually spaced hues for track ids; golden-ratio stepping keeps
#: consecutive ids visually distinct instead of nearly identical.
_GOLDEN_RATIO = 0.618033988749895


def track_color(index: int) -> tuple[int, int, int]:
    """Deterministic, well-separated RGB colour for a track or class index."""
    hue = (index * _GOLDEN_RATIO) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255))


def label_color(confidence: float) -> tuple[int, int, int]:
    """Red -> amber -> green by confidence."""
    confidence = float(np.clip(confidence, 0.0, 1.0))
    # Hue 0 (red) to 1/3 (green).
    r, g, b = colorsys.hsv_to_rgb(confidence / 3.0, 0.85, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255))


def _format(m: Measured | None, show_sigma: bool, unit_scale: float = 1.0, unit: str = "m") -> str:
    """Render a measured value for drawing onto a frame.

    ASCII only. OpenCV's ``putText`` uses Hershey vector fonts, which have no
    glyphs outside ASCII -- a '±' is drawn byte-by-byte from its UTF-8
    encoding and comes out as 'Â±' on the image.
    """
    if m is None:
        return "-"
    value = m.value * unit_scale
    sigma = m.sigma * unit_scale
    digits = 3 if abs(value) < 10 else 2
    if show_sigma and sigma > 0:
        return f"{value:.{digits}f}+/-{sigma:.{digits}f}{unit}"
    return f"{value:.{digits}f}{unit}"


def _object_lines(
    obj: ObjectMeasurement, style: AnnotationStyle, *, compact: bool = False
) -> list[str]:
    """Text block for one object.

    ``compact`` collapses everything onto one line -- used automatically on
    crowded frames, where the full four-line panel per object covers more of
    the image than it explains.
    """
    if compact:
        name = obj.detection.label
        if style.show_track_id and obj.track_id is not None:
            name = f"#{obj.track_id} {name}"
        if obj.dimensions is None:
            return [f"{name}: n/a"]
        d = obj.dimensions
        return [
            f"{name} {d.length.value:.2f}x{d.width.value:.2f}x{d.height.value:.2f}m"
            f" ({obj.confidence:.0%})"
        ]

    lines: list[str] = []

    header = obj.detection.label
    if style.show_track_id and obj.track_id is not None:
        header = f"#{obj.track_id} {header}"
    if style.show_confidence:
        header += f" ({obj.confidence:.0%})"
    lines.append(header)

    if style.show_dimensions and obj.dimensions is not None:
        d = obj.dimensions
        sigma = style.show_uncertainty
        lines.append(
            f"{_format(d.length, False)} x {_format(d.width, False)} x {_format(d.height, False)}"
        )
        if sigma:
            # The largest dimension, not the worst relative error: a
            # near-degenerate axis divides by ~0 and would render an absurd
            # percentage over the frame.
            principal = max(d.length, d.width, d.height, key=lambda m: m.value)
            lines.append(f"+/-{principal.relative_error:.1%}")

    if style.show_distance and obj.distance is not None:
        lines.append(f"d={_format(obj.distance, style.show_uncertainty)}")

    if style.show_volume and obj.volume is not None:
        litres = obj.volume.value * 1000.0
        lines.append(f"V={litres:.1f}L")

    if obj.dimensions is None and obj.warnings:
        lines.append("not measurable")

    return lines


def _place_labels(
    anchors: list[tuple[int, int, int, int]], frame_size: tuple[int, int], top: int = 0
) -> list[tuple[int, int]]:
    """Nudge label boxes downward until they stop overlapping.

    A greedy top-to-bottom sweep is enough here and is stable frame to frame,
    which matters more than optimality -- labels that jitter between positions
    are harder to read than labels that are slightly misplaced.
    """
    width, height = frame_size
    placed: list[tuple[int, int, int, int]] = []
    positions: list[tuple[int, int]] = []

    for x, y, w, h in anchors:
        px, py = x, y
        for _ in range(24):
            rect = (px, py, w, h)
            if not any(_overlaps(rect, other) for other in placed):
                break
            py += h + 4
            if py + h > height:
                py = max(0, y - h - 4)
                break
        px = int(np.clip(px, 0, max(0, width - w)))
        py = int(np.clip(py, top, max(top, height - h)))
        placed.append((px, py, w, h))
        positions.append((px, py))
    return positions


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def draw_scene(
    image: NDArray[np.uint8],
    scene: SceneMeasurement,
    *,
    masks: list[NDArray[np.bool_]] | None = None,
    intrinsics: CameraIntrinsics | None = None,
    style: AnnotationStyle | None = None,
) -> NDArray[np.uint8]:
    """Render a scene's measurements onto a copy of the frame.

    Args:
        image: RGB frame.
        scene: Measurements to draw.
        masks: Optional instance masks, index-aligned with ``scene.objects``.
        intrinsics: Needed to project the 3-D boxes; omit to skip them.
        style: Appearance overrides.

    Returns:
        A new annotated RGB image; the input is not modified.
    """
    style = style or AnnotationStyle()
    canvas = image.copy()
    height, width = canvas.shape[:2]

    if style.show_masks and masks:
        overlay = canvas.copy()
        for i, mask in enumerate(masks):
            if i >= len(scene.objects) or mask is None or not mask.any():
                continue
            colour = track_color(scene.objects[i].track_id or i)
            overlay[mask] = colour
        cv2.addWeighted(overlay, style.mask_alpha, canvas, 1 - style.mask_alpha, 0, canvas)

    # Decide which objects get a text label. Boxes and masks are drawn for
    # everything; only the panels are rationed, because they are what occludes
    # the image. Largest-on-screen wins, as that is what a viewer is looking at.
    order = sorted(
        range(len(scene.objects)),
        key=lambda i: scene.objects[i].detection.bbox.area,
        reverse=True,
    )
    labelled = set(order[: max(0, style.max_labels)])
    compact = style.compact_labels if style.compact_labels is not None else len(labelled) > 5

    anchors: list[tuple[int, int, int, int]] = []
    per_object_lines: list[list[str]] = []
    label_indices: list[int] = []

    for i, obj in enumerate(scene.objects):
        colour = track_color(obj.track_id or i)
        box = obj.detection.bbox
        x1, y1, x2, y2 = (round(v) for v in box.as_tuple())

        dim = obj.confidence < style.min_confidence
        thickness = 1 if dim else style.box_thickness
        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, thickness)

        if (
            style.show_3d_box
            and intrinsics is not None
            and obj.dimensions is not None
            and obj.confidence >= style.box_3d_min_confidence
        ):
            _draw_3d_box(canvas, obj, intrinsics, colour)

        if i not in labelled:
            # Unlabelled objects still get an index tag so the box can be
            # matched to its entry in the JSON.
            cv2.putText(
                canvas,
                str(i),
                (x1 + 3, y1 + 14),
                style.font,
                style.font_scale,
                colour,
                style.thickness,
                cv2.LINE_AA,
            )
            continue

        lines = _object_lines(obj, style, compact=compact)
        per_object_lines.append(lines)
        label_indices.append(i)

        line_h = int(18 * (style.font_scale / 0.45))
        text_w = max(
            cv2.getTextSize(line, style.font, style.font_scale, style.thickness)[0][0]
            for line in lines
        )
        box_w = text_w + 10
        box_h = line_h * len(lines) + 6
        anchors.append((x1, max(style.reserved_top_px, y1 - box_h - 2), box_w, box_h))

    positions = _place_labels(anchors, (width, height), top=style.reserved_top_px)

    for slot, index in enumerate(label_indices):
        obj = scene.objects[index]
        lines = per_object_lines[slot]
        px, py = positions[slot]
        _, _, box_w, box_h = anchors[slot]
        accent = label_color(obj.confidence)

        # Solid backing plate: text over a busy photo is unreadable otherwise.
        cv2.rectangle(canvas, (px, py), (px + box_w, py + box_h), (24, 24, 24), -1)
        cv2.rectangle(canvas, (px, py), (px + box_w, py + box_h), accent, 1)

        line_h = int(18 * (style.font_scale / 0.45))
        for j, line in enumerate(lines):
            colour = accent if j == 0 else (235, 235, 235)
            cv2.putText(
                canvas,
                line,
                (px + 5, py + line_h * (j + 1) - 4),
                style.font,
                style.font_scale,
                colour,
                style.thickness,
                cv2.LINE_AA,
            )

    _draw_footer(canvas, scene, style)
    return canvas


def _draw_3d_box(
    canvas: NDArray[np.uint8],
    obj: ObjectMeasurement,
    intrinsics: CameraIntrinsics,
    colour: tuple[int, int, int],
) -> None:
    """Project and draw the oriented bounding box wireframe."""
    dims = obj.dimensions
    if dims is None or dims.axes is None or dims.origin is None:
        return

    extents = np.array([dims.length.value, dims.width.value, dims.height.value])
    signs = np.array(
        [[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], dtype=np.float64
    )
    corners = dims.origin + (signs * extents * 0.5) @ dims.axes

    # Anything at or behind the image plane cannot be projected meaningfully.
    if np.any(corners[:, 2] <= 1e-3):
        return

    projected = intrinsics.project(corners).astype(int)
    edges = [
        (0, 1),
        (0, 2),
        (0, 4),
        (1, 3),
        (1, 5),
        (2, 3),
        (2, 6),
        (3, 7),
        (4, 5),
        (4, 6),
        (5, 7),
        (6, 7),
    ]
    for a, b in edges:
        cv2.line(canvas, tuple(projected[a]), tuple(projected[b]), colour, 1, cv2.LINE_AA)


def _draw_footer(
    canvas: NDArray[np.uint8], scene: SceneMeasurement, style: AnnotationStyle
) -> None:
    """Frame-level status strip."""
    height, width = canvas.shape[:2]
    total_ms = scene.timings_ms.get("total", 0.0)
    fps = 1000.0 / total_ms if total_ms > 0 else 0.0

    parts = [
        f"frame {scene.frame_index}",
        f"{len(scene.objects)} obj",
        f"{total_ms:.0f}ms ({fps:.1f} fps)",
        f"calib: {scene.calibration_source}",
    ]
    if scene.ground_plane is not None:
        parts.append(f"plane {scene.ground_plane.inlier_ratio:.0%}")
    text = "  |  ".join(parts)

    (text_w, text_h), _ = cv2.getTextSize(text, style.font, 0.45, 1)
    cv2.rectangle(canvas, (0, height - text_h - 10), (text_w + 12, height), (18, 18, 18), -1)
    cv2.putText(
        canvas,
        text,
        (6, height - 6),
        style.font,
        0.45,
        (200, 220, 200),
        1,
        cv2.LINE_AA,
    )

    # Surface the loudest scene-level caveat rather than burying it in JSON.
    if scene.calibration_source == "assumed_fov":
        warning = "UNCALIBRATED - scale approximate"
        (w_w, w_h), _ = cv2.getTextSize(warning, style.font, 0.5, 2)
        cv2.rectangle(canvas, (width - w_w - 14, 0), (width, w_h + 12), (140, 20, 20), -1)
        cv2.putText(
            canvas,
            warning,
            (width - w_w - 7, w_h + 4),
            style.font,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )


def draw_depth_map(
    depth: NDArray[np.float32],
    *,
    colormap: int = cv2.COLORMAP_TURBO,
    near: float | None = None,
    far: float | None = None,
) -> NDArray[np.uint8]:
    """Colourise a metric depth map for inspection.

    Percentile-based normalisation is used rather than min/max: a handful of
    sky pixels at 200 m would otherwise compress the entire useful range into a
    couple of colour steps.
    """
    valid = np.isfinite(depth) & (depth > 0)
    if not valid.any():
        return np.zeros((*depth.shape, 3), dtype=np.uint8)

    lo = near if near is not None else float(np.percentile(depth[valid], 2))
    hi = far if far is not None else float(np.percentile(depth[valid], 98))
    if hi <= lo:
        hi = lo + 1e-3

    normalised = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
    coloured = cv2.applyColorMap((normalised * 255).astype(np.uint8), colormap)
    coloured[~valid] = 0
    return cv2.cvtColor(coloured, cv2.COLOR_BGR2RGB)
