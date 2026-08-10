"""Result serialisation: JSON, CSV, COCO and NDJSON.

Format choice by use case:

* **JSON** -- one scene, complete, including uncertainties and provenance.
* **NDJSON** -- one line per frame, appended as a video is processed. Streams
  to disk with flat memory and stays readable if the job is interrupted, which
  a single top-level JSON array does not.
* **CSV** -- one row per object, for spreadsheets and quick analysis. Nested
  structure is flattened into explicit columns.
* **COCO** -- masks as RLE, for feeding annotation tools or training sets.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.core.types import ObjectMeasurement, SceneMeasurement

__all__ = [
    "NdjsonWriter",
    "encode_rle",
    "scene_to_coco",
    "scene_to_csv",
    "scene_to_json",
    "write_csv",
    "write_json",
]

CSV_COLUMNS = [
    "frame_index",
    "timestamp",
    "track_id",
    "label",
    "score",
    "confidence",
    "length_m",
    "length_sigma_m",
    "width_m",
    "width_sigma_m",
    "height_m",
    "height_sigma_m",
    "volume_m3",
    "volume_sigma_m3",
    "volume_method",
    "surface_area_m2",
    "footprint_area_m2",
    "distance_m",
    "distance_sigma_m",
    "nearest_distance_m",
    "position_x",
    "position_y",
    "position_z",
    "mask_area_px",
    "point_count",
    "calibration_source",
    "warnings",
]


def scene_to_json(scene: SceneMeasurement, *, indent: int | None = 2) -> str:
    """Serialise one scene, with a provenance envelope."""
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "units": {"length": "m", "area": "m^2", "volume": "m^3"},
        "scene": scene.to_dict(),
    }
    return json.dumps(payload, indent=indent, default=_fallback)


def _fallback(value: Any) -> Any:
    """Make numpy scalars and arrays JSON-serialisable."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


def write_json(path: str | Path, scene: SceneMeasurement, *, indent: int | None = 2) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(scene_to_json(scene, indent=indent), encoding="utf-8")
    return out


def _object_row(obj: ObjectMeasurement, scene: SceneMeasurement) -> dict[str, Any]:
    dims = obj.dimensions
    position = obj.position if obj.position is not None else (None, None, None)
    return {
        "frame_index": scene.frame_index,
        "timestamp": round(scene.timestamp, 4),
        "track_id": obj.track_id,
        "label": obj.detection.label,
        "score": round(obj.detection.score, 4),
        "confidence": round(obj.confidence, 4),
        "length_m": _v(dims.length) if dims else None,
        "length_sigma_m": _s(dims.length) if dims else None,
        "width_m": _v(dims.width) if dims else None,
        "width_sigma_m": _s(dims.width) if dims else None,
        "height_m": _v(dims.height) if dims else None,
        "height_sigma_m": _s(dims.height) if dims else None,
        "volume_m3": _v(obj.volume),
        "volume_sigma_m3": _s(obj.volume),
        "volume_method": obj.volume.method.value if obj.volume and obj.volume.method else None,
        "surface_area_m2": _v(obj.surface_area),
        "footprint_area_m2": _v(obj.footprint_area),
        "distance_m": _v(obj.distance),
        "distance_sigma_m": _s(obj.distance),
        "nearest_distance_m": _v(obj.nearest_distance),
        "position_x": _round(position[0]),
        "position_y": _round(position[1]),
        "position_z": _round(position[2]),
        "mask_area_px": obj.mask_area_px,
        "point_count": obj.point_count,
        "calibration_source": scene.calibration_source,
        # Semicolons, not commas: commas would need quoting and make the field
        # painful to split downstream.
        "warnings": "; ".join(obj.warnings),
    }


def _v(m: Any) -> float | None:
    return round(float(m.value), 6) if m is not None else None


def _s(m: Any) -> float | None:
    return round(float(m.sigma), 6) if m is not None else None


def _round(value: Any) -> float | None:
    return round(float(value), 5) if value is not None else None


def scene_to_csv(scenes: Sequence[SceneMeasurement], *, header: bool = True) -> str:
    """Flatten one or more scenes into CSV text."""
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    if header:
        writer.writeheader()
    for scene in scenes:
        for obj in scene.objects:
            writer.writerow(_object_row(obj, scene))
    return buffer.getvalue()


def write_csv(path: str | Path, scenes: Sequence[SceneMeasurement]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is required or csv emits blank rows between records on Windows.
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for scene in scenes:
            for obj in scene.objects:
                writer.writerow(_object_row(obj, scene))
    return out


class NdjsonWriter:
    """Append one JSON object per frame.

    Used for long videos: memory stays flat and a partially written file is
    still fully parseable up to the last complete line.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8")
        self._count = 0

    def write(self, scene: SceneMeasurement) -> None:
        self._handle.write(json.dumps(scene.to_dict(), default=_fallback) + "\n")
        self._count += 1
        # Flush periodically so a crashed job leaves usable output, without
        # paying a syscall per frame.
        if self._count % 20 == 0:
            self._handle.flush()

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.flush()
            self._handle.close()

    def __enter__(self) -> NdjsonWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# COCO
# ---------------------------------------------------------------------------
def encode_rle(mask: NDArray[np.bool_]) -> dict[str, Any]:
    """COCO-style uncompressed RLE (column-major run lengths).

    Implemented directly rather than via ``pycocotools`` so mask export has no
    compiled dependency. The column-major order and leading zero-run are part
    of the COCO format, not an implementation choice.
    """
    flat = np.asfortranarray(mask.astype(np.uint8)).ravel(order="F")
    if flat.size == 0:
        return {"size": list(mask.shape), "counts": []}

    # Run boundaries: positions where the value changes.
    changes = np.flatnonzero(np.diff(flat)) + 1
    boundaries = np.concatenate([[0], changes, [flat.size]])
    lengths = np.diff(boundaries).tolist()

    # COCO counts always start with a run of zeros; prepend an empty one when
    # the mask begins with foreground.
    if flat[0] == 1:
        lengths = [0, *lengths]

    return {"size": [int(mask.shape[0]), int(mask.shape[1])], "counts": lengths}


def decode_rle(rle: dict[str, Any]) -> NDArray[np.bool_]:
    """Inverse of :func:`encode_rle`; used to verify round-tripping."""
    height, width = rle["size"]
    flat = np.zeros(height * width, dtype=np.uint8)
    position = 0
    value = 0
    for length in rle["counts"]:
        if value:
            flat[position : position + length] = 1
        position += length
        value ^= 1
    return flat.reshape((height, width), order="F").astype(bool)


def scene_to_coco(
    scenes: Sequence[SceneMeasurement],
    masks_per_scene: Sequence[Sequence[NDArray[np.bool_]]] | None = None,
    *,
    image_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build a COCO-format dict, carrying measurements as custom fields.

    Measurements live under a namespaced ``measurecv`` key on each annotation
    so the file stays valid COCO for any standard tool while remaining
    lossless for ours.
    """
    images: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []
    categories: dict[str, int] = {}
    annotation_id = 1

    for index, scene in enumerate(scenes):
        image_id = index + 1
        images.append(
            {
                "id": image_id,
                "file_name": (
                    image_names[index]
                    if image_names and index < len(image_names)
                    else f"frame_{scene.frame_index:06d}.jpg"
                ),
                "width": scene.image_size[0],
                "height": scene.image_size[1],
            }
        )

        scene_masks = (
            masks_per_scene[index] if masks_per_scene and index < len(masks_per_scene) else None
        )

        for obj_index, obj in enumerate(scene.objects):
            label = obj.detection.label
            if label not in categories:
                categories[label] = len(categories) + 1

            box = obj.detection.bbox
            annotation: dict[str, Any] = {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": categories[label],
                "bbox": [
                    round(box.x1, 2),
                    round(box.y1, 2),
                    round(box.width, 2),
                    round(box.height, 2),
                ],
                "area": round(box.area, 2),
                "iscrowd": 0,
                "score": round(obj.detection.score, 4),
                "measurecv": {
                    "track_id": obj.track_id,
                    "confidence": round(obj.confidence, 4),
                    "dimensions": obj.dimensions.to_dict() if obj.dimensions else None,
                    "volume": obj.volume.to_dict() if obj.volume else None,
                    "distance": obj.distance.to_dict() if obj.distance else None,
                    "warnings": obj.warnings,
                },
            }
            if scene_masks and obj_index < len(scene_masks):
                annotation["segmentation"] = encode_rle(scene_masks[obj_index])

            annotations.append(annotation)
            annotation_id += 1

    return {
        "info": {
            "description": "measurecv metric measurements",
            "version": "1.0",
            "date_created": datetime.now(UTC).isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": i, "name": name} for name, i in sorted(categories.items(), key=lambda kv: kv[1])
        ],
    }


def write_coco(path: str | Path, scenes: Sequence[SceneMeasurement], **kwargs: Any) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(scene_to_coco(scenes, **kwargs), indent=2, default=_fallback), encoding="utf-8"
    )
    return out


def summarise(scenes: Iterable[SceneMeasurement]) -> dict[str, Any]:
    """Aggregate statistics across a run, for the CLI summary line."""
    frames = 0
    objects = 0
    measured = 0
    confidences: list[float] = []
    labels: dict[str, int] = {}

    for scene in scenes:
        frames += 1
        for obj in scene.objects:
            objects += 1
            labels[obj.detection.label] = labels.get(obj.detection.label, 0) + 1
            confidences.append(obj.confidence)
            if obj.dimensions is not None:
                measured += 1

    return {
        "frames": frames,
        "objects": objects,
        "measured": measured,
        "measured_fraction": round(measured / objects, 4) if objects else 0.0,
        "mean_confidence": round(float(np.mean(confidences)), 4) if confidences else 0.0,
        "labels": dict(sorted(labels.items(), key=lambda kv: -kv[1])),
    }
