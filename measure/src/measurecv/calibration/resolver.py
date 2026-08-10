"""Deciding which camera model to use for a given image.

The pipeline needs intrinsics for *every* frame, including ones from an unknown
phone with no calibration. This module implements the fallback ladder --
calibrated profile, then caller-supplied, then EXIF, then an assumed FOV -- and
records which rung was used so the result is auditable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import (
    CameraIntrinsics,
    intrinsics_from_exif,
    intrinsics_from_fov,
)
from measurecv.core.config import CalibrationConfig
from measurecv.core.exceptions import CalibrationError
from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["IntrinsicsResolver", "read_exif", "undistort_image"]


def read_exif(path: str | Path) -> dict[str, Any]:
    """Extract EXIF tags as a name-keyed dict. Never raises."""
    try:
        from PIL import ExifTags, Image

        with Image.open(path) as img:
            raw = img.getexif()
            if not raw:
                return {}
            tags: dict[str, Any] = {}
            for tag_id, value in raw.items():
                tags[ExifTags.TAGS.get(tag_id, str(tag_id))] = value
            # The lens/camera sub-IFD holds FocalLengthIn35mmFilm on most phones.
            try:
                for tag_id, value in raw.get_ifd(0x8769).items():
                    tags[ExifTags.TAGS.get(tag_id, str(tag_id))] = value
            except Exception:  # pragma: no cover - depends on file
                pass
            return tags
    except Exception as exc:  # pragma: no cover - corrupt/missing EXIF is normal
        log.debug("exif_read_failed", path=str(path), error=str(exc))
        return {}


class IntrinsicsResolver:
    """Resolves intrinsics for incoming frames, with caching.

    A single resolver instance is shared by the pipeline. Profiles are loaded
    once; per-resolution rescalings are memoised because the pipeline asks for
    them on every frame.
    """

    def __init__(self, config: CalibrationConfig) -> None:
        self._config = config
        self._profile: CameraIntrinsics | None = None
        self._cache: dict[tuple[int, int, str], CameraIntrinsics] = {}

        if config.profile is not None:
            self._profile = CameraIntrinsics.load(config.profile)
            log.info(
                "calibration_profile_loaded",
                path=str(config.profile),
                fx=round(self._profile.fx, 2),
                size=f"{self._profile.width}x{self._profile.height}",
                rms=round(self._profile.rms_reprojection_error, 3),
            )

    @property
    def profile(self) -> CameraIntrinsics | None:
        return self._profile

    def set_profile(self, intrinsics: CameraIntrinsics) -> None:
        """Install a profile at runtime (used by the calibration API)."""
        self._profile = intrinsics
        self._cache.clear()
        log.info("calibration_profile_set", source=intrinsics.source.value)

    def resolve(
        self,
        width: int,
        height: int,
        *,
        exif: dict[str, Any] | None = None,
        override: CameraIntrinsics | None = None,
    ) -> CameraIntrinsics:
        """Return intrinsics valid for a ``width`` x ``height`` frame."""
        if override is not None:
            return self._fit(override, width, height)

        key = (width, height, "profile" if self._profile else ("exif" if exif else "fov"))
        cached = self._cache.get(key)
        if cached is not None and not exif:
            return cached

        result: CameraIntrinsics | None = None

        if self._profile is not None:
            result = self._fit(self._profile, width, height)
        elif exif and self._config.allow_exif:
            result = intrinsics_from_exif(exif, width, height)
            if result is not None:
                log.debug("intrinsics_from_exif", fx=round(result.fx, 1))

        if result is None:
            result = intrinsics_from_fov(width, height, self._config.default_hfov_deg)
            log.warning(
                "intrinsics_assumed",
                hfov_deg=self._config.default_hfov_deg,
                impact="absolute scale uncertain to ~15%; calibrate for metrology-grade results",
            )

        if not exif:
            self._cache[key] = result
        return result

    def _fit(self, base: CameraIntrinsics, width: int, height: int) -> CameraIntrinsics:
        """Adapt a profile to the actual frame size.

        Pure rescaling is only valid when the aspect ratio matches. A different
        aspect ratio means the sensor was cropped rather than scaled, and
        blindly stretching the intrinsics would introduce a systematic error --
        so that case is refused loudly.
        """
        if (base.width, base.height) == (width, height):
            return base

        src_ar = base.width / base.height
        dst_ar = width / height
        if abs(src_ar - dst_ar) > 0.02:
            raise CalibrationError(
                f"calibration profile is {base.width}x{base.height} (AR {src_ar:.3f}) but the "
                f"frame is {width}x{height} (AR {dst_ar:.3f}). Differing aspect ratios imply a "
                "sensor crop, which cannot be recovered by scaling. Re-calibrate at the capture "
                "resolution.",
                profile_size=[base.width, base.height],
                frame_size=[width, height],
            )
        return base.scaled(width, height)


def undistort_image(
    image: NDArray[np.uint8], intrinsics: CameraIntrinsics
) -> tuple[NDArray[np.uint8], CameraIntrinsics]:
    """Rectify lens distortion, returning the image and its new camera model.

    ``alpha=0`` is used so the output contains only valid pixels: black
    in-fill regions would be interpreted as real surface by the depth model.
    The principal point moves as a result, which is why the updated intrinsics
    must be used downstream rather than the originals.
    """
    if not intrinsics.has_distortion:
        return image, intrinsics

    h, w = image.shape[:2]
    new_k, _roi = cv2.getOptimalNewCameraMatrix(
        intrinsics.K, intrinsics.distortion, (w, h), alpha=0.0, newImgSize=(w, h)
    )
    rectified = cv2.undistort(image, intrinsics.K, intrinsics.distortion, None, new_k)
    updated = CameraIntrinsics(
        fx=float(new_k[0, 0]),
        fy=float(new_k[1, 1]),
        cx=float(new_k[0, 2]),
        cy=float(new_k[1, 2]),
        width=w,
        height=h,
        distortion=np.zeros(5),
        source=intrinsics.source,
        focal_uncertainty=intrinsics.focal_uncertainty,
        rms_reprojection_error=intrinsics.rms_reprojection_error,
        metadata={**intrinsics.metadata, "rectified": True},
    )
    return rectified, updated
