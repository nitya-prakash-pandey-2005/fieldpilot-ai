"""
Metric calibration for Agent 2 — converting pixels into millimetres.

Three strategies, in the priority order system_prompt.md §Agent-2 specifies:

  1. ARUCO      — a printed marker of known size lying in (or near) the plane of
                  the thing being measured. Gives a full plane homography, so
                  measurement stays correct under perspective. Highest accuracy.
  2. REFERENCE  — a known object (hard hat, standard brick, A4 sheet) detected in
                  frame. Single uniform px/mm scale, no perspective correction.
  3. DEPTH      — monocular metric depth + camera intrinsics. Works with no props
                  at all, which is the realistic glasses case, but is the least
                  accurate and reports that honestly in its confidence.

The important difference from a naive "pixels per mm" scalar: strategy 1 returns
a *homography*, which maps image points onto the marker's physical plane in mm.
A scalar px/mm ratio is only valid at one depth and one viewing angle; on a rebar
grid photographed at any realistic angle it is wrong by 10-30%, which is larger
than the tolerance we are trying to check.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

# Default marker: DICT_4X4_50, id 0, printed at exactly 100mm.
# Generate with: python models/training/make_aruco.py --id 0 --size-mm 100
ARUCO_DICT_NAME = os.getenv("ARUCO_DICT", "DICT_4X4_50")
ARUCO_MARKER_MM = float(os.getenv("ARUCO_MARKER_MM", "100.0"))

# Known reference objects, longest visible dimension in mm. Used only when no
# marker is present. Values are nominal — hence the lower confidence attached.
REFERENCE_OBJECTS_MM = {
    "hardhat": 280.0,        # front-to-back length of a standard EN397 shell
    "brick": 190.0,          # standard modular brick length (India IS 1077 / 190mm)
    "a4_sheet": 297.0,       # long edge
    "safety_cone_450": 450.0,
    "person": 1700.0,        # standing height — very rough, last resort
}

# Horizontal field of view by capture device, for the depth strategy's focal
# length estimate. Override with CAMERA_HFOV_DEG for a specific camera.
DEVICE_HFOV_DEG = {
    "webcam": 65.0,
    "phone": 68.0,
    "meta_glasses": 90.0,    # Ray-Ban Meta Gen 2 wide capture
}


@dataclass
class Calibration:
    """The result of calibrating one frame.

    Use `to_mm(p1, p2)` for a distance; do not multiply by `px_per_mm` directly
    unless `method == 'reference'`, because for the homography path there is no
    single valid scalar.
    """
    method: str                              # 'aruco' | 'reference' | 'depth' | 'none'
    confidence: float                        # 0..1, honest about method accuracy
    homography: Optional[np.ndarray] = None  # image px -> plane mm (aruco only)
    px_per_mm: Optional[float] = None        # scalar scale (reference; aruco approx)
    depth_map: Optional[np.ndarray] = None   # metres per pixel (depth only)
    focal_px: Optional[float] = None         # estimated focal length (depth only)
    detail: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.method != "none"

    def to_mm(self, p1: tuple[float, float], p2: tuple[float, float]) -> Optional[float]:
        """Metric distance between two image points, in millimetres."""
        if self.method == "aruco" and self.homography is not None:
            a, b = self._project(p1), self._project(p2)
            return float(math.dist(a, b))

        if self.method == "reference" and self.px_per_mm:
            return float(math.dist(p1, p2) / self.px_per_mm)

        if self.method == "depth" and self.depth_map is not None and self.focal_px:
            z1 = self._depth_at(p1)
            z2 = self._depth_at(p2)
            if z1 is None or z2 is None:
                return None
            # Back-project both points to camera-space metres, then take the
            # true 3D distance. Using a single average depth (the common
            # shortcut) is only valid for a fronto-parallel pair and silently
            # under-reports any distance with a depth component.
            P1 = self._backproject(p1, z1)
            P2 = self._backproject(p2, z2)
            return float(math.dist(P1, P2) * 1000.0)

        return None

    # -- internals ---------------------------------------------------------

    def _project(self, p: tuple[float, float]) -> tuple[float, float]:
        v = np.array([p[0], p[1], 1.0], dtype=np.float64)
        w = self.homography @ v
        if abs(w[2]) < 1e-9:
            return (float("inf"), float("inf"))
        return (float(w[0] / w[2]), float(w[1] / w[2]))

    def _depth_at(self, p: tuple[float, float], win: int = 2) -> Optional[float]:
        """Median depth in a small window — a single pixel on a thin rebar edge
        frequently lands on the background and reads metres too far."""
        h, w = self.depth_map.shape[:2]
        x, y = int(round(p[0])), int(round(p[1]))
        if not (0 <= x < w and 0 <= y < h):
            return None
        patch = self.depth_map[max(0, y - win):y + win + 1, max(0, x - win):x + win + 1]
        if patch.size == 0:
            return None
        z = float(np.median(patch))
        return z if z > 0.05 else None

    def _backproject(self, p: tuple[float, float], z: float) -> tuple[float, float, float]:
        cx = self.detail.get("cx", 0.0)
        cy = self.detail.get("cy", 0.0)
        f = self.focal_px
        return ((p[0] - cx) * z / f, (p[1] - cy) * z / f, z)


# ---------------------------------------------------------------------------
# Strategy 1 — ArUco
# ---------------------------------------------------------------------------

class ArucoCalibrator:
    def __init__(self, dict_name: str = ARUCO_DICT_NAME, marker_mm: float = ARUCO_MARKER_MM):
        self.marker_mm = marker_mm
        dictionary = cv2.aruco.getPredefinedDictionary(
            getattr(cv2.aruco, dict_name, cv2.aruco.DICT_4X4_50)
        )
        params = cv2.aruco.DetectorParameters()
        # Sub-pixel corner refinement. Without it, corner error is ~1px, which at
        # a typical 2 px/mm working scale is already a 0.5mm error per corner
        # before anything else goes wrong.
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        params.cornerRefinementWinSize = 5
        self.detector = cv2.aruco.ArucoDetector(dictionary, params)

    # OpenCV rejects any marker candidate whose contour comes within a few
    # pixels of the frame border, so a marker near the edge of a wide-FOV
    # glasses frame is silently dropped — measured behaviour: a 200px marker
    # detects reliably at >=20px from the edge and never at <=10px, at any
    # resolution. Padding the frame with replicated edge pixels before detection
    # rescues it completely; corners are shifted back afterwards so every
    # coordinate downstream stays in original-image space.
    _BORDER_PAD = 24

    def calibrate(self, image: np.ndarray) -> Optional[Calibration]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

        pad = self._BORDER_PAD
        padded = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        corners, ids, _ = self.detector.detectMarkers(padded)
        if ids is None or len(corners) == 0:
            return None
        corners = [c - np.float32([pad, pad]) for c in corners]

        # OpenCV 4.x returns ids shaped (N, 1); 5.x returns (N,). Flatten so the
        # marker-id lookup below works on both.
        ids_flat = np.asarray(ids).reshape(-1)

        # If several markers are visible, use the largest — it is the closest and
        # its corners carry the least relative error.
        areas = [cv2.contourArea(c[0].astype(np.float32)) for c in corners]
        best = int(np.argmax(areas))
        img_pts = corners[best][0].astype(np.float32)          # TL, TR, BR, BL
        S = self.marker_mm
        world_pts = np.array([[0, 0], [S, 0], [S, S], [0, S]], dtype=np.float32)

        H = cv2.getPerspectiveTransform(img_pts, world_pts)

        # Sanity: round-trip the marker corners through H and check we recover the
        # square. A marker detected on a curled sheet or at a grazing angle can
        # produce a numerically valid but physically useless homography.
        rt = cv2.perspectiveTransform(img_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
        residual_mm = float(np.mean(np.linalg.norm(rt - world_pts, axis=1)))

        side_px = float(np.mean([
            np.linalg.norm(img_pts[i] - img_pts[(i + 1) % 4]) for i in range(4)
        ]))
        px_per_mm = side_px / S

        # Skew: ratio of the two diagonals. 1.0 is head-on; beyond ~1.35 the
        # marker is so oblique that out-of-plane error dominates.
        d1 = np.linalg.norm(img_pts[0] - img_pts[2])
        d2 = np.linalg.norm(img_pts[1] - img_pts[3])
        skew = float(max(d1, d2) / max(min(d1, d2), 1e-6))

        confidence = 0.97
        if residual_mm > 1.0:
            confidence -= min(residual_mm / 20.0, 0.25)
        if skew > 1.35:
            confidence -= min((skew - 1.35) * 0.4, 0.30)
        if side_px < 40:
            confidence -= 0.20        # marker too small in frame to trust
        confidence = round(max(confidence, 0.35), 3)

        return Calibration(
            method="aruco",
            confidence=confidence,
            homography=H,
            px_per_mm=px_per_mm,
            detail={
                "marker_id": int(ids_flat[best]),
                "marker_mm": S,
                "marker_side_px": round(side_px, 2),
                "reprojection_residual_mm": round(residual_mm, 3),
                "skew_ratio": round(skew, 3),
                "markers_found": int(len(corners)),
            },
        )


# ---------------------------------------------------------------------------
# Strategy 2 — known reference object
# ---------------------------------------------------------------------------

def calibrate_from_reference(bbox: dict, object_type: str,
                             known_mm: Optional[float] = None) -> Optional[Calibration]:
    """Scale from a detected object of known real size.

    `bbox` is the {x1,y1,x2,y2} dict the vision pipeline already produces, so
    this plugs straight into Agent 1's output with no extra detection pass.
    """
    mm = known_mm or REFERENCE_OBJECTS_MM.get(object_type)
    if not mm:
        return None
    w = abs(float(bbox["x2"]) - float(bbox["x1"]))
    h = abs(float(bbox["y2"]) - float(bbox["y1"]))
    longest_px = max(w, h)
    if longest_px < 20:
        return None

    px_per_mm = longest_px / mm
    # Nominal-size objects vary: hard hats differ by brand, "person" is a guess.
    confidence = {"brick": 0.80, "a4_sheet": 0.85, "hardhat": 0.70,
                  "safety_cone_450": 0.72, "person": 0.45}.get(object_type, 0.65)

    return Calibration(
        method="reference",
        confidence=confidence,
        px_per_mm=px_per_mm,
        detail={"reference_object": object_type, "assumed_mm": mm,
                "measured_px": round(longest_px, 1),
                "caveat": "uniform scale — no perspective correction; "
                          "accurate only for objects at the reference's depth"},
    )


# ---------------------------------------------------------------------------
# Strategy 3 — monocular metric depth
# ---------------------------------------------------------------------------

def calibrate_from_depth(depth_map: np.ndarray, image_shape: tuple,
                         device: str = "webcam",
                         hfov_deg: Optional[float] = None) -> Calibration:
    """Build a calibration from a metric depth map (metres per pixel).

    Focal length is estimated from the assumed horizontal FOV rather than a real
    intrinsic calibration, so this is the least accurate path. It exists because
    it is the only one that needs no props — which is the realistic case for a
    worker glancing at a wall.
    """
    h, w = image_shape[:2]
    fov = hfov_deg or float(os.getenv("CAMERA_HFOV_DEG", 0)) or DEVICE_HFOV_DEG.get(device, 65.0)
    focal_px = (w / 2.0) / math.tan(math.radians(fov / 2.0))

    valid = float(np.mean((depth_map > 0.05) & (depth_map < 50.0))) if depth_map.size else 0.0
    confidence = round(min(0.62, 0.62 * valid), 3)

    return Calibration(
        method="depth",
        confidence=confidence,
        depth_map=depth_map,
        focal_px=focal_px,
        detail={
            "assumed_hfov_deg": fov,
            "focal_px": round(focal_px, 1),
            "device": device,
            "valid_depth_fraction": round(valid, 3),
            # principal point — _backproject reads these out of detail
            "cx": w / 2.0,
            "cy": h / 2.0,
            "caveat": "focal length assumed from device FOV, not intrinsically "
                      "calibrated; place an ArUco marker for tolerance-grade accuracy",
        },
    )
