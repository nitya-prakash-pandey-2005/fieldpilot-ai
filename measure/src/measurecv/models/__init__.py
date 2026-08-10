"""Neural backends behind narrow, swappable interfaces.

Concrete backends are imported lazily by :class:`~measurecv.models.manager.ModelManager`
so that importing this package never pulls in torch.
"""

from measurecv.models.base import DepthEstimator, Detector, ModelBase, Segmenter
from measurecv.models.manager import ModelManager

__all__ = ["DepthEstimator", "Detector", "ModelBase", "ModelManager", "Segmenter"]
