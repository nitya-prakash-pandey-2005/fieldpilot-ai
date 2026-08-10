"""The camera model.

Everything downstream of depth estimation is a function of the intrinsics, so
this module is deliberately strict: intrinsics carry their *provenance* and an
*uncertainty*, and both propagate into the final error bars.

Why provenance matters
----------------------
A measurement made with a properly calibrated camera and one made with a
guessed 60-degree field of view are not the same product, but they look
identical in a JSON payload. :attr:`CameraIntrinsics.source` and
:attr:`CameraIntrinsics.focal_uncertainty` make the difference explicit and
quantitative -- a guessed FOV carries ~15% focal uncertainty, which correctly
widens every reported dimension's error bar by the same fraction.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.core.exceptions import CalibrationError
from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["CameraIntrinsics", "IntrinsicsSource", "intrinsics_from_exif", "intrinsics_from_fov"]


class IntrinsicsSource(StrEnum):
    """Where the camera model came from, best first."""

    CALIBRATED = "calibrated"
    """Zhang's method on a physical target. ~1% focal uncertainty."""

    METADATA = "exif"
    """Derived from EXIF focal length + sensor size. ~5%."""

    PROVIDED = "provided"
    """Supplied by the caller; trusted at the stated uncertainty."""

    ASSUMED_FOV = "assumed_fov"
    """Fallback guess. ~15% -- honest, but wide."""


#: Default relative 1-sigma focal-length uncertainty per provenance class.
_DEFAULT_FOCAL_SIGMA: dict[IntrinsicsSource, float] = {
    IntrinsicsSource.CALIBRATED: 0.01,
    IntrinsicsSource.METADATA: 0.05,
    IntrinsicsSource.PROVIDED: 0.02,
    IntrinsicsSource.ASSUMED_FOV: 0.15,
}


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """Pinhole intrinsics with optional Brown-Conrady distortion.

    Attributes:
        fx, fy: Focal lengths in pixels.
        cx, cy: Principal point in pixels.
        width, height: Image size these intrinsics are valid for. Intrinsics
            are resolution-dependent, so carrying the size prevents the classic
            bug of applying full-res intrinsics to a resized frame.
        distortion: ``(k1, k2, p1, p2, k3)`` OpenCV coefficients.
        source: Provenance.
        focal_uncertainty: Relative 1-sigma of ``fx``/``fy``.
        rms_reprojection_error: Calibration residual in pixels, if known.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
    distortion: NDArray[np.float64] = field(default_factory=lambda: np.zeros(5, dtype=np.float64))
    source: IntrinsicsSource = IntrinsicsSource.PROVIDED
    focal_uncertainty: float = 0.02
    rms_reprojection_error: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.fx <= 0 or self.fy <= 0:
            raise CalibrationError(f"focal lengths must be positive: fx={self.fx}, fy={self.fy}")
        if self.width <= 0 or self.height <= 0:
            raise CalibrationError(f"invalid image size: {self.width}x{self.height}")
        if not 0.0 <= self.focal_uncertainty < 1.0:
            raise CalibrationError(f"focal_uncertainty out of range: {self.focal_uncertainty}")
        # A principal point far outside the frame indicates a unit or ordering
        # mistake and would silently skew every back-projection.
        if not (-self.width <= self.cx <= 2 * self.width):
            raise CalibrationError(
                f"principal point cx={self.cx} implausible for width {self.width}"
            )
        if not (-self.height <= self.cy <= 2 * self.height):
            raise CalibrationError(
                f"principal point cy={self.cy} implausible for height {self.height}"
            )
        object.__setattr__(
            self, "distortion", np.asarray(self.distortion, dtype=np.float64).ravel()
        )

    # -- derived quantities -------------------------------------------------
    @property
    def K(self) -> NDArray[np.float64]:
        """3x3 camera matrix."""
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    @property
    def K_inv(self) -> NDArray[np.float64]:
        """Closed-form inverse -- cheaper and better conditioned than a solve."""
        return np.array(
            [
                [1.0 / self.fx, 0.0, -self.cx / self.fx],
                [0.0, 1.0 / self.fy, -self.cy / self.fy],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )

    @property
    def has_distortion(self) -> bool:
        return bool(np.any(np.abs(self.distortion) > 1e-9))

    @property
    def hfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.width / (2.0 * self.fx)))

    @property
    def vfov_deg(self) -> float:
        return math.degrees(2.0 * math.atan(self.height / (2.0 * self.fy)))

    @property
    def aspect_ratio_error(self) -> float:
        """``|fx/fy - 1|``. Real sensors have square pixels; a large value here
        usually means a stretched or letter-boxed image.
        """
        return abs(self.fx / self.fy - 1.0)

    # -- geometric transforms ----------------------------------------------
    def scaled(self, new_width: int, new_height: int) -> CameraIntrinsics:
        """Intrinsics for a resized image.

        Focal length and principal point scale linearly with resolution.
        Distortion coefficients are normalised quantities and are unchanged.
        """
        sx = new_width / self.width
        sy = new_height / self.height
        return CameraIntrinsics(
            fx=self.fx * sx,
            fy=self.fy * sy,
            # Pixel centres: a pixel at index u spans [u, u+1), so the correct
            # mapping of a *coordinate* is (u + 0.5) * s - 0.5.
            cx=(self.cx + 0.5) * sx - 0.5,
            cy=(self.cy + 0.5) * sy - 0.5,
            width=new_width,
            height=new_height,
            distortion=self.distortion.copy(),
            source=self.source,
            focal_uncertainty=self.focal_uncertainty,
            rms_reprojection_error=self.rms_reprojection_error * math.sqrt(sx * sy),
            metadata=dict(self.metadata),
        )

    def cropped(self, x0: int, y0: int, width: int, height: int) -> CameraIntrinsics:
        """Intrinsics for a crop: focal unchanged, principal point shifts."""
        return CameraIntrinsics(
            fx=self.fx,
            fy=self.fy,
            cx=self.cx - x0,
            cy=self.cy - y0,
            width=width,
            height=height,
            distortion=self.distortion.copy(),
            source=self.source,
            focal_uncertainty=self.focal_uncertainty,
            rms_reprojection_error=self.rms_reprojection_error,
            metadata=dict(self.metadata),
        )

    def undistorted(self) -> CameraIntrinsics:
        """Model for an already-rectified image (zero distortion)."""
        return CameraIntrinsics(
            fx=self.fx,
            fy=self.fy,
            cx=self.cx,
            cy=self.cy,
            width=self.width,
            height=self.height,
            distortion=np.zeros(5),
            source=self.source,
            focal_uncertainty=self.focal_uncertainty,
            rms_reprojection_error=self.rms_reprojection_error,
            metadata={**self.metadata, "rectified": True},
        )

    # -- projection ---------------------------------------------------------
    def backproject(
        self, u: NDArray[np.float64], v: NDArray[np.float64], z: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        """Lift pixel coordinates with known depth into camera-frame 3-D points.

        ``z`` is depth along the optical axis, matching Metric3D's output
        convention.

        Returns:
            ``(N, 3)`` array of ``(X, Y, Z)`` in metres.
        """
        x = (u - self.cx) * z / self.fx
        y = (v - self.cy) * z / self.fy
        return np.stack([x, y, z], axis=-1)

    def project(self, points: NDArray[np.float64]) -> NDArray[np.float64]:
        """Project camera-frame points to pixels (no distortion applied)."""
        z = np.clip(points[:, 2], 1e-9, None)
        u = points[:, 0] * self.fx / z + self.cx
        v = points[:, 1] * self.fy / z + self.cy
        return np.stack([u, v], axis=-1)

    def ray_directions(self, u: NDArray[np.float64], v: NDArray[np.float64]) -> NDArray[np.float64]:
        """Unit view rays through the given pixels."""
        dirs = np.stack(
            [(u - self.cx) / self.fx, (v - self.cy) / self.fy, np.ones_like(u)], axis=-1
        )
        return dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)

    def pixel_solid_angle_area(self, z: NDArray[np.float64]) -> NDArray[np.float64]:
        """Metric area subtended by one pixel at depth ``z``, for a surface
        perpendicular to the optical axis: ``z^2 / (fx * fy)``.

        Slant correction (dividing by ``cos theta``) is applied separately by
        the surface-area estimator, which knows the local normal.
        """
        return z * z / (self.fx * self.fy)

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "width": self.width,
            "height": self.height,
            "distortion": self.distortion.tolist(),
            "source": self.source.value,
            "focal_uncertainty": self.focal_uncertainty,
            "rms_reprojection_error": self.rms_reprojection_error,
            "hfov_deg": round(self.hfov_deg, 3),
            "vfov_deg": round(self.vfov_deg, 3),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CameraIntrinsics:
        known = {
            "fx",
            "fy",
            "cx",
            "cy",
            "width",
            "height",
            "distortion",
            "source",
            "focal_uncertainty",
            "rms_reprojection_error",
            "metadata",
        }
        payload = {k: v for k, v in data.items() if k in known}
        if "distortion" in payload:
            payload["distortion"] = np.asarray(payload["distortion"], dtype=np.float64)
        if "source" in payload:
            payload["source"] = IntrinsicsSource(payload["source"])
        try:
            return cls(**payload)
        except TypeError as exc:
            raise CalibrationError(f"malformed intrinsics record: {exc}") from exc

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        log.info("intrinsics_saved", path=str(p), source=self.source.value)

    @classmethod
    def load(cls, path: str | Path) -> CameraIntrinsics:
        p = Path(path)
        if not p.is_file():
            raise CalibrationError(f"calibration profile not found: {p}", path=str(p))
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))


def intrinsics_from_fov(
    width: int,
    height: int,
    hfov_deg: float = 60.0,
    vfov_deg: float | None = None,
) -> CameraIntrinsics:
    """Build intrinsics from a field-of-view assumption.

    Square pixels are assumed unless ``vfov_deg`` is given explicitly, because
    deriving ``fy`` from the image aspect ratio is only valid if the sensor was
    not cropped -- and assuming square pixels is the safer error.
    """
    if not 1.0 < hfov_deg < 179.0:
        raise CalibrationError(f"hfov_deg out of range: {hfov_deg}")
    fx = width / (2.0 * math.tan(math.radians(hfov_deg) / 2.0))
    fy = height / (2.0 * math.tan(math.radians(vfov_deg) / 2.0)) if vfov_deg is not None else fx
    return CameraIntrinsics(
        fx=fx,
        fy=fy,
        cx=(width - 1) / 2.0,
        cy=(height - 1) / 2.0,
        width=width,
        height=height,
        source=IntrinsicsSource.ASSUMED_FOV,
        focal_uncertainty=_DEFAULT_FOCAL_SIGMA[IntrinsicsSource.ASSUMED_FOV],
        metadata={"assumed_hfov_deg": hfov_deg},
    )


# Diagonal of a 35 mm frame, used to convert 35 mm-equivalent focal lengths.
_FULL_FRAME_DIAGONAL_MM = math.hypot(36.0, 24.0)


def intrinsics_from_exif(exif: dict[str, Any], width: int, height: int) -> CameraIntrinsics | None:
    """Derive intrinsics from EXIF metadata, or ``None`` if insufficient.

    Two routes, in order of reliability:

    1. ``FocalLengthIn35mmFilm`` -- already normalised for sensor size, so it
       yields the focal length in pixels directly.
    2. ``FocalLength`` (mm) plus ``FocalPlaneXResolution`` -- gives physical
       sensor width, from which pixels-per-mm follows.

    A bare ``FocalLength`` with no sensor information is *not* enough, and this
    function returns ``None`` rather than inventing a sensor size.
    """
    f35 = exif.get("FocalLengthIn35mmFilm") or exif.get("FocalLengthIn35mmFormat")
    if f35:
        try:
            f35_mm = float(f35)
        except (TypeError, ValueError):
            f35_mm = 0.0
        if f35_mm > 0:
            # The 35 mm-equivalent focal is defined by the *diagonal* FOV, so
            # convert through the image diagonal in pixels, not the width.
            diagonal_px = math.hypot(width, height)
            fpx = f35_mm * diagonal_px / _FULL_FRAME_DIAGONAL_MM
            return CameraIntrinsics(
                fx=fpx,
                fy=fpx,
                cx=(width - 1) / 2.0,
                cy=(height - 1) / 2.0,
                width=width,
                height=height,
                source=IntrinsicsSource.METADATA,
                focal_uncertainty=_DEFAULT_FOCAL_SIGMA[IntrinsicsSource.METADATA],
                metadata={"exif_focal_35mm": f35_mm},
            )

    focal_mm = exif.get("FocalLength")
    xres = exif.get("FocalPlaneXResolution")
    unit = exif.get("FocalPlaneResolutionUnit", 2)  # 2 = inch, 3 = cm
    if focal_mm and xres:
        try:
            focal_mm_f = float(focal_mm)
            xres_f = float(xres)
        except (TypeError, ValueError):
            return None
        if focal_mm_f <= 0 or xres_f <= 0:
            return None
        mm_per_unit = 25.4 if int(unit) == 2 else 10.0
        pixels_per_mm = xres_f / mm_per_unit
        # FocalPlaneXResolution refers to the sensor's native pixel pitch; if
        # the image was downscaled, rescale to the actual width.
        native_width = float(exif.get("ExifImageWidth") or exif.get("PixelXDimension") or width)
        pixels_per_mm *= width / native_width if native_width > 0 else 1.0
        fpx = focal_mm_f * pixels_per_mm
        if fpx <= 0:
            return None
        return CameraIntrinsics(
            fx=fpx,
            fy=fpx,
            cx=(width - 1) / 2.0,
            cy=(height - 1) / 2.0,
            width=width,
            height=height,
            source=IntrinsicsSource.METADATA,
            focal_uncertainty=_DEFAULT_FOCAL_SIGMA[IntrinsicsSource.METADATA],
            metadata={"exif_focal_mm": focal_mm_f, "focal_plane_x_res": xres_f},
        )

    return None


def default_focal_sigma(source: IntrinsicsSource) -> float:
    """Recommended relative focal uncertainty for a provenance class."""
    return _DEFAULT_FOCAL_SIGMA[source]
