"""Intrinsic calibration from a planar target (Zhang's method).

Chessboard *and* ChArUco are supported. ChArUco is the better default when
available: the ArUco markers identify each corner uniquely, so partially
visible boards still contribute observations, which makes it far easier to
cover the image corners -- and corner coverage is what actually constrains the
distortion coefficients.

Quality gates
-------------
A calibration that "succeeds" with a 3-pixel reprojection error is worse than
no calibration, because it will be trusted. :func:`calibrate_from_images`
therefore enforces a configurable RMS ceiling and reports per-view residuals so
bad views can be identified and removed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from measurecv.calibration.intrinsics import CameraIntrinsics, IntrinsicsSource
from measurecv.core.exceptions import CalibrationError
from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["CalibrationResult", "calibrate_from_images", "detect_board", "make_object_points"]

_TERM_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 1e-6)


@dataclass(slots=True)
class CalibrationResult:
    """Outcome of a calibration run."""

    intrinsics: CameraIntrinsics
    rms_error: float
    per_view_errors: list[float] = field(default_factory=list)
    accepted_views: list[str] = field(default_factory=list)
    rejected_views: list[tuple[str, str]] = field(default_factory=list)
    coverage: float = 0.0
    """Fraction of the image area spanned by the union of detected corners.
    Below ~0.5 the distortion estimate is extrapolating."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intrinsics": self.intrinsics.to_dict(),
            "rms_error": round(self.rms_error, 4),
            "per_view_errors": [round(e, 4) for e in self.per_view_errors],
            "accepted_views": self.accepted_views,
            "rejected_views": [{"path": p, "reason": r} for p, r in self.rejected_views],
            "coverage": round(self.coverage, 4),
        }


def make_object_points(board_shape: tuple[int, int], square_size_m: float) -> NDArray[np.float32]:
    """Planar model points for a chessboard, Z = 0, in metres."""
    cols, rows = board_shape
    grid = np.zeros((cols * rows, 3), dtype=np.float32)
    grid[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    return grid * square_size_m


def _charuco_board(
    board_shape: tuple[int, int], square_size_m: float, marker_size_m: float, dict_name: str
) -> tuple[Any, Any]:
    """Build a ChArUco board across OpenCV 4.7+ and legacy APIs."""
    if not hasattr(cv2, "aruco"):
        raise CalibrationError(
            "ChArUco requires opencv-contrib-python; install it or use board_type='chessboard'"
        )
    aruco = cv2.aruco
    if not hasattr(aruco, dict_name):
        raise CalibrationError(f"unknown ArUco dictionary: {dict_name}")
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, dict_name))
    cols, rows = board_shape
    # ChArUco counts *squares*; inner corners are (cols-1, rows-1).
    if hasattr(aruco, "CharucoBoard") and hasattr(aruco.CharucoBoard, "generateImage"):
        board = aruco.CharucoBoard((cols, rows), square_size_m, marker_size_m, dictionary)
    else:  # pragma: no cover - legacy OpenCV
        board = aruco.CharucoBoard_create(cols, rows, square_size_m, marker_size_m, dictionary)
    return board, dictionary


def detect_board(
    image: NDArray[np.uint8],
    board_shape: tuple[int, int],
    square_size_m: float,
    *,
    board_type: str = "chessboard",
    marker_size_m: float = 0.018,
    dict_name: str = "DICT_4X4_50",
    refine: bool = True,
) -> tuple[NDArray[np.float32], NDArray[np.float32]] | None:
    """Detect target corners in one image.

    Returns:
        ``(object_points, image_points)`` or ``None`` when the board is absent.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image

    if board_type == "charuco":
        board, dictionary = _charuco_board(board_shape, square_size_m, marker_size_m, dict_name)
        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
            corners, ids, _ = detector.detectMarkers(gray)
        else:  # pragma: no cover - legacy OpenCV
            corners, ids, _ = cv2.aruco.detectMarkers(gray, dictionary)
        if ids is None or len(ids) < 4:
            return None
        retval, ch_corners, ch_ids = cv2.aruco.interpolateCornersCharuco(corners, ids, gray, board)
        if not retval or ch_corners is None or len(ch_corners) < 6:
            return None
        all_obj = board.getChessboardCorners()
        obj = np.asarray(all_obj, dtype=np.float32)[ch_ids.ravel()]
        return obj, ch_corners.reshape(-1, 2).astype(np.float32)

    # Chessboard. The SB ("sector based") detector is markedly more robust to
    # blur and uneven lighting than the classic one; fall back if unavailable.
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
    found, corners = False, None
    if hasattr(cv2, "findChessboardCornersSB"):
        found, corners = cv2.findChessboardCornersSB(
            gray, board_shape, flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
        )
    if not found:
        found, corners = cv2.findChessboardCorners(gray, board_shape, flags=flags)
        if found and refine:
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), _TERM_CRITERIA)
    if not found or corners is None:
        return None

    return make_object_points(board_shape, square_size_m), corners.reshape(-1, 2).astype(np.float32)


def _coverage(image_points: Sequence[NDArray[np.float32]], width: int, height: int) -> float:
    """Fraction of the frame covered by the convex hull of all corners."""
    if not image_points:
        return 0.0
    stacked = np.concatenate(image_points, axis=0).astype(np.float32)
    if stacked.shape[0] < 3:
        return 0.0
    hull = cv2.convexHull(stacked)
    return float(cv2.contourArea(hull) / (width * height))


def calibrate_from_images(
    images: Sequence[NDArray[np.uint8]],
    board_shape: tuple[int, int],
    square_size_m: float,
    *,
    names: Sequence[str] | None = None,
    board_type: str = "chessboard",
    marker_size_m: float = 0.018,
    dict_name: str = "DICT_4X4_50",
    min_views: int = 8,
    max_rms_error_px: float = 1.0,
    fix_aspect_ratio: bool = True,
    rational_model: bool = False,
) -> CalibrationResult:
    """Run Zhang's calibration over a set of target images.

    Args:
        images: RGB frames containing the target.
        board_shape: Inner corners ``(cols, rows)`` for a chessboard, or
            squares ``(cols, rows)`` for ChArUco.
        square_size_m: Physical square size. **The accuracy of every downstream
            measurement is proportional to the accuracy of this number** --
            measure the printed target, do not trust the nominal value.
        fix_aspect_ratio: Constrain ``fx == fy``. Correct for essentially all
            modern sensors and it removes a degenerate direction that otherwise
            absorbs noise.
        rational_model: Enable ``k4..k6``; only worth it for fisheye-ish lenses
            with many well-distributed views.

    Raises:
        CalibrationError: Too few usable views, or residual above the ceiling.
    """
    if len(images) < min_views:
        raise CalibrationError(
            f"need at least {min_views} views, got {len(images)}",
            required=min_views,
            provided=len(images),
        )

    names = list(names or [f"view_{i}" for i in range(len(images))])
    height, width = images[0].shape[:2]

    obj_points: list[NDArray[np.float32]] = []
    img_points: list[NDArray[np.float32]] = []
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []

    for image, name in zip(images, names, strict=False):
        if image.shape[:2] != (height, width):
            rejected.append((name, f"size mismatch {image.shape[1]}x{image.shape[0]}"))
            continue
        found = detect_board(
            image,
            board_shape,
            square_size_m,
            board_type=board_type,
            marker_size_m=marker_size_m,
            dict_name=dict_name,
        )
        if found is None:
            rejected.append((name, "board not detected"))
            continue
        obj, img = found
        obj_points.append(obj)
        img_points.append(img)
        accepted.append(name)

    if len(obj_points) < min_views:
        raise CalibrationError(
            f"board detected in only {len(obj_points)}/{len(images)} views "
            f"(need {min_views}); check lighting, focus and board_shape",
            detected=len(obj_points),
            rejected=rejected,
        )

    flags = 0
    if fix_aspect_ratio:
        flags |= cv2.CALIB_FIX_ASPECT_RATIO
    if rational_model:
        flags |= cv2.CALIB_RATIONAL_MODEL

    # Seed with a sane guess so the optimiser starts in the right basin.
    init_f = max(width, height) * 0.9
    init_k = np.array(
        [[init_f, 0, (width - 1) / 2.0], [0, init_f, (height - 1) / 2.0], [0, 0, 1]],
        dtype=np.float64,
    )
    flags |= cv2.CALIB_USE_INTRINSIC_GUESS

    rms, camera_matrix, dist, rvecs, tvecs = cv2.calibrateCamera(
        [o.reshape(-1, 1, 3) for o in obj_points],
        [p.reshape(-1, 1, 2) for p in img_points],
        (width, height),
        init_k,
        np.zeros(5),
        flags=flags,
        criteria=_TERM_CRITERIA,
    )

    per_view: list[float] = []
    for i, (obj, img) in enumerate(zip(obj_points, img_points, strict=True)):
        projected, _ = cv2.projectPoints(obj, rvecs[i], tvecs[i], camera_matrix, dist)
        err = float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - img) ** 2, axis=1))))
        per_view.append(err)

    if rms > max_rms_error_px:
        worst = int(np.argmax(per_view))
        raise CalibrationError(
            f"calibration RMS {rms:.3f}px exceeds limit {max_rms_error_px}px; "
            f"worst view '{accepted[worst]}' at {per_view[worst]:.3f}px. "
            "Re-shoot with a rigid, flat board and varied orientations.",
            rms=rms,
            per_view_errors=per_view,
        )

    coverage = _coverage(img_points, width, height)
    if coverage < 0.4:
        log.warning(
            "low_calibration_coverage",
            coverage=round(coverage, 3),
            hint="include views with the board near the image corners",
        )

    # Focal uncertainty scales with the residual: a 0.2px RMS calibration is
    # genuinely better than a 0.9px one, and the error bars should say so.
    focal_sigma = float(np.clip(0.002 + 0.010 * rms, 0.002, 0.05))

    intrinsics = CameraIntrinsics(
        fx=float(camera_matrix[0, 0]),
        fy=float(camera_matrix[1, 1]),
        cx=float(camera_matrix[0, 2]),
        cy=float(camera_matrix[1, 2]),
        width=width,
        height=height,
        distortion=np.asarray(dist, dtype=np.float64).ravel()[:5],
        source=IntrinsicsSource.CALIBRATED,
        focal_uncertainty=focal_sigma,
        rms_reprojection_error=float(rms),
        metadata={
            "views": len(obj_points),
            "board_type": board_type,
            "board_shape": list(board_shape),
            "square_size_m": square_size_m,
            "coverage": round(coverage, 4),
        },
    )

    log.info(
        "calibration_complete",
        rms=round(float(rms), 4),
        views=len(obj_points),
        fx=round(intrinsics.fx, 2),
        hfov=round(intrinsics.hfov_deg, 2),
        coverage=round(coverage, 3),
    )

    return CalibrationResult(
        intrinsics=intrinsics,
        rms_error=float(rms),
        per_view_errors=per_view,
        accepted_views=accepted,
        rejected_views=rejected,
        coverage=coverage,
    )


def calibrate_from_paths(paths: Sequence[str | Path], **kwargs: Any) -> CalibrationResult:
    """Convenience wrapper reading images from disk."""
    images: list[NDArray[np.uint8]] = []
    names: list[str] = []
    for path in paths:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            log.warning("calibration_image_unreadable", path=str(path))
            continue
        images.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        names.append(Path(path).name)
    if not images:
        raise CalibrationError("no readable calibration images", paths=[str(p) for p in paths])
    return calibrate_from_images(images, names=names, **kwargs)
