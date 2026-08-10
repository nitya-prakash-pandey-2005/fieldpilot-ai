"""Constant-velocity Kalman filter for bounding boxes.

State: ``[cx, cy, s, r, vx, vy, vs]`` where ``s`` is box area and ``r`` the
aspect ratio.

Area is tracked instead of width and height because for a rigid object moving
towards or away from the camera, area changes smoothly with depth while aspect
ratio stays nearly constant. Modelling aspect as a constant (no velocity term)
therefore encodes a true physical prior and keeps the filter from inventing
box distortions during occlusion -- which is exactly when the prediction is
carrying the track on its own.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from measurecv.core.types import BoundingBox

__all__ = ["KalmanBoxTracker"]


class KalmanBoxTracker:
    """Tracks one box. Standard SORT formulation with tuned noise."""

    _next_id: int = 1

    def __init__(self, box: BoundingBox) -> None:
        self.id = KalmanBoxTracker._next_id
        KalmanBoxTracker._next_id += 1

        self.time_since_update = 0
        self.hits = 1
        self.hit_streak = 1
        self.age = 0

        # x_{k+1} = F x_k
        self._F = np.eye(7)
        for i in range(3):
            self._F[i, i + 4] = 1.0

        # z = H x  (we observe position and shape, not velocity)
        self._H = np.zeros((4, 7))
        self._H[:4, :4] = np.eye(4)

        self._P = np.eye(7)
        # Velocities are unobserved at birth, so start them with high variance
        # and let the first few associations pull them in.
        self._P[4:, 4:] *= 1000.0
        self._P *= 10.0

        self._Q = np.eye(7)
        self._Q[4:, 4:] *= 0.01  # motion is close to constant velocity
        self._Q[-1, -1] *= 0.01  # scale changes slowly

        self._R = np.eye(4)
        self._R[2:, 2:] *= 10.0  # area/aspect measurements are noisier than centre

        self._x = np.zeros((7, 1))
        self._x[:4, 0] = _to_state(box)

    # -- filter ------------------------------------------------------------
    def predict(self) -> BoundingBox:
        """Advance one step and return the predicted box."""
        # Guard against the area going negative, which would make the box
        # width imaginary when converting back.
        if self._x[6, 0] + self._x[2, 0] <= 0:
            self._x[6, 0] = 0.0

        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + self._Q

        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        return _to_box(self._x[:4, 0])

    def update(self, box: BoundingBox) -> None:
        """Correct with an observed box."""
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1

        z = _to_state(box).reshape(4, 1)
        y = z - self._H @ self._x
        # Capitals follow the standard Kalman notation (S: innovation
        # covariance, K: gain); renaming them to satisfy a style rule would
        # make this harder to check against any reference.
        S = self._H @ self._P @ self._H.T + self._R
        K = self._P @ self._H.T @ np.linalg.inv(S)

        self._x = self._x + K @ y
        identity = np.eye(7)
        # Joseph form would be more numerically robust, but with a 7-state
        # filter and well-conditioned R the simple form is stable and cheaper.
        self._P = (identity - K @ self._H) @ self._P

    @property
    def state(self) -> BoundingBox:
        return _to_box(self._x[:4, 0])


def _to_state(box: BoundingBox) -> NDArray[np.float64]:
    """``xyxy`` -> ``[cx, cy, area, aspect]``."""
    w = max(box.width, 1e-6)
    h = max(box.height, 1e-6)
    cx, cy = box.centre
    return np.array([cx, cy, w * h, w / h], dtype=np.float64)


def _to_box(state: NDArray[np.float64]) -> BoundingBox:
    """``[cx, cy, area, aspect]`` -> ``xyxy``."""
    cx, cy, area, aspect = state
    area = max(float(area), 1e-6)
    aspect = max(float(aspect), 1e-6)
    w = np.sqrt(area * aspect)
    h = area / w if w > 0 else 1e-3
    return BoundingBox(float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2))
