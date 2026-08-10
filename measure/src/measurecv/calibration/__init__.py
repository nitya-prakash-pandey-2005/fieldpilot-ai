"""Camera calibration: intrinsics, target-based calibration, scale refinement."""

from measurecv.calibration.board import (
    CalibrationResult,
    calibrate_from_images,
    calibrate_from_paths,
    detect_board,
)
from measurecv.calibration.intrinsics import (
    CameraIntrinsics,
    IntrinsicsSource,
    intrinsics_from_exif,
    intrinsics_from_fov,
)
from measurecv.calibration.resolver import IntrinsicsResolver, read_exif, undistort_image
from measurecv.calibration.scale import (
    ScaleCorrection,
    estimate_scale_correction,
    known_reference_sizes,
    scale_from_reference_dimension,
)

__all__ = [
    "CalibrationResult",
    "CameraIntrinsics",
    "IntrinsicsResolver",
    "IntrinsicsSource",
    "ScaleCorrection",
    "calibrate_from_images",
    "calibrate_from_paths",
    "detect_board",
    "estimate_scale_correction",
    "intrinsics_from_exif",
    "intrinsics_from_fov",
    "known_reference_sizes",
    "read_exif",
    "scale_from_reference_dimension",
    "undistort_image",
]
