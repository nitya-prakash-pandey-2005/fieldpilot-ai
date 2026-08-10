"""SAM 2 instance segmentation backend.

Why segmentation quality is the accuracy lever here
---------------------------------------------------
A detection box is not a measurement primitive. Back-projecting the pixels
inside a box would include background at a completely different depth, and
since background pixels sit at the extremes of the resulting point cloud they
would dominate every extent estimate. The mask is what makes the point cloud
*be* the object.

SAM 2 is prompted with the RT-DETR boxes rather than run in "segment
everything" mode: the boxes already encode which objects matter, and
box-prompted decoding costs one cheap decoder pass per object against a single
shared image embedding.

Two SAM outputs feed the confidence model directly:

* ``iou_scores`` -- SAM's own prediction of its mask quality.
* a *stability score*, computed here by thresholding the mask logits at
  +/- delta and comparing the resulting areas. A mask whose area swings wildly
  with a small threshold change has an ambiguous boundary, which translates
  directly into an uncertain silhouette and therefore an uncertain dimension.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from measurecv.core.config import SegmentationConfig
from measurecv.core.device import DeviceContext, autocast_context
from measurecv.core.exceptions import ModelLoadError
from measurecv.core.logging import get_logger
from measurecv.core.types import BoundingBox, InstanceMask
from measurecv.models.base import Segmenter

log = get_logger(__name__)

__all__ = ["Sam2Segmenter"]

#: Logit offset used for the stability score. SAM's mask logits are calibrated
#: around 0, so +/-1 probes the boundary region without leaving it.
_STABILITY_DELTA = 1.0


class Sam2Segmenter(Segmenter):
    """SAM 2.1 via HuggingFace ``transformers``."""

    def __init__(self, config: SegmentationConfig, device: DeviceContext | None = None) -> None:
        super().__init__(device)
        self._config = config
        self._model: Any = None
        self._processor: Any = None

    @property
    def name(self) -> str:
        return f"sam2:{self._config.model_id}"

    def _load(self) -> None:
        try:
            import torch
            from transformers import Sam2Model, Sam2Processor
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ModelLoadError(
                "SAM 2 needs the 'models' extra: pip install 'measurecv[models]'",
                missing=str(exc),
            ) from exc

        model_id = self._config.model_id
        try:
            self._processor = Sam2Processor.from_pretrained(model_id)
            model = Sam2Model.from_pretrained(model_id)
        except Exception as exc:
            raise ModelLoadError(
                f"could not load SAM 2 weights '{model_id}': {exc}", model_id=model_id
            ) from exc

        model.eval()
        model.to(self._device.torch_device)
        if self._device.is_cuda:
            model = model.to(memory_format=torch.channels_last)
            if self._device.dtype_name != "fp32":
                model = model.to(self._device.torch_dtype)

        self._model = model

    def _unload(self) -> None:
        self._model = None
        self._processor = None

    def segment(
        self,
        image: NDArray[np.uint8],
        boxes: Sequence[BoundingBox],
        *,
        points: Sequence[tuple[float, float]] | None = None,
    ) -> list[InstanceMask]:
        """Segment every box in a single forward pass.

        All prompts share one image encoding -- the Hiera encoder dominates SAM
        2's cost and is prompt-independent, so running it once for N objects
        instead of N times is the difference between a usable and an unusable
        frame rate on crowded scenes.
        """
        self.ensure_loaded()
        if not boxes:
            return []

        import torch

        height, width = image.shape[:2]
        cfg = self._config

        padded = (
            [b.expand(cfg.box_prompt_padding, width, height) for b in boxes]
            if cfg.box_prompt_padding > 0
            else list(boxes)
        )
        box_list = [[list(b.as_tuple()) for b in padded]]

        processor_kwargs: dict[str, Any] = {
            "images": image,
            "input_boxes": box_list,
            "return_tensors": "pt",
        }

        if cfg.use_point_prompt:
            # One positive point per object at the box centre. Shapes follow the
            # processor contract: points are
            # (batch, num_objects, num_points_per_object, 2) and labels
            # (batch, num_objects, num_points_per_object), with label 1 meaning
            # "foreground". This disambiguates crowded boxes, where the box
            # alone leaves SAM unsure which of several overlapping objects is
            # intended.
            centres = [[list(b.centre)] for b in padded]
            processor_kwargs["input_points"] = [centres]
            processor_kwargs["input_labels"] = [[[1] for _ in padded]]

        inputs = self._processor(**processor_kwargs)
        inputs = {
            k: (v.to(self._device.torch_device) if hasattr(v, "to") else v)
            for k, v in inputs.items()
        }
        if self._device.is_cuda and self._device.dtype_name != "fp32" and "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(self._device.torch_dtype)

        original_sizes = inputs.get("original_sizes")
        forward_inputs = {k: v for k, v in inputs.items() if k != "original_sizes"}

        with torch.inference_mode(), autocast_context(self._device):
            outputs = self._model(**forward_inputs, multimask_output=cfg.multimask_output)

        return self._decode(outputs, original_sizes, len(boxes), (height, width))

    # -- decoding ----------------------------------------------------------
    def _decode(
        self,
        outputs: Any,
        original_sizes: Any,
        n_objects: int,
        frame_shape: tuple[int, int],
    ) -> list[InstanceMask]:
        import torch

        cfg = self._config
        height, width = frame_shape

        if original_sizes is None:
            original_sizes = torch.tensor([[height, width]])

        # Keep logits (binarize=False) so the stability score can be computed
        # before thresholding destroys the information.
        logits = self._processor.post_process_masks(
            outputs.pred_masks.float().cpu(),
            original_sizes,
            binarize=False,
        )
        if isinstance(logits, list):
            logits = logits[0]
        logits = torch.as_tensor(logits)

        iou_scores = outputs.iou_scores.float().detach().cpu()
        # Expected (batch, objects, hypotheses); tolerate a squeezed batch dim.
        while iou_scores.dim() > 2:
            iou_scores = (
                iou_scores[0]
                if iou_scores.shape[0] == 1
                else iou_scores.reshape(-1, iou_scores.shape[-1])
            )
        while logits.dim() > 4:
            logits = logits[0]
        if logits.dim() == 3:  # single object, hypotheses collapsed
            logits = logits.unsqueeze(0)

        results: list[InstanceMask] = []
        for i in range(n_objects):
            if i >= logits.shape[0]:
                results.append(self._empty_mask(frame_shape))
                continue

            object_logits = logits[i]  # (hypotheses, H, W)
            scores = (
                iou_scores[i] if i < iou_scores.shape[0] else torch.ones(object_logits.shape[0])
            )

            # With multimask_output SAM returns three hypotheses at different
            # granularities (part / subpart / whole). Its own predicted IoU is
            # the intended selector, and picking the best costs nothing because
            # all three come out of the same decoder pass.
            best = int(torch.argmax(scores[: object_logits.shape[0]]).item())
            chosen = object_logits[best]

            mask = (chosen > cfg.mask_logit_threshold).numpy().astype(bool)
            stability = _stability_score(chosen, cfg.mask_logit_threshold)

            mask = _cleanup(mask, cfg)

            if int(mask.sum()) < cfg.min_mask_area_px:
                log.debug("mask_below_min_area", index=i, area=int(mask.sum()))
                results.append(
                    InstanceMask(mask=mask, iou_score=float(scores[best]), stability=stability)
                )
                continue

            results.append(
                InstanceMask(
                    mask=mask,
                    iou_score=float(scores[best].item()),
                    stability=stability,
                )
            )

        return results

    @staticmethod
    def _empty_mask(shape: tuple[int, int]) -> InstanceMask:
        """Placeholder that preserves index alignment with the detections."""
        return InstanceMask(mask=np.zeros(shape, dtype=bool), iou_score=0.0, stability=0.0)

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "model_id": self._config.model_id,
            "multimask_output": self._config.multimask_output,
        }


def _stability_score(logits: Any, threshold: float, delta: float = _STABILITY_DELTA) -> float:
    """Ratio of mask areas at a high and a low logit threshold.

    A crisp boundary gives a ratio near 1; a soft, ambiguous one gives a much
    smaller value. This is the same statistic SAM's own automatic mask
    generator uses to filter low-quality masks, and it is a better predictor of
    silhouette error than the predicted IoU alone.
    """
    high = (logits > threshold + delta).sum().item()
    low = (logits > threshold - delta).sum().item()
    if low <= 0:
        return 0.0
    return float(min(1.0, high / low))


def _cleanup(mask: NDArray[np.bool_], cfg: SegmentationConfig) -> NDArray[np.bool_]:
    """Fill pinholes and drop specks.

    Both distort measurement in opposite directions: pinholes remove valid
    interior samples and inflate the apparent boundary length (which the
    boundary-shrink estimator would then misread), while specks add points at
    the wrong depth outside the object.
    """
    import cv2

    if not mask.any():
        return mask

    if cfg.fill_holes_px > 0:
        # Flood-fill from the border: whatever the fill cannot reach is an
        # enclosed hole. Small ones are filled, large ones are left alone since
        # they are usually genuine (a handle, a gap in a chair back).
        inverted = (~mask).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=4)
        border_labels = (
            set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
        )
        for label in range(1, count):
            if label in border_labels:
                continue
            if stats[label, cv2.CC_STAT_AREA] <= cfg.fill_holes_px:
                mask = mask | (labels == label)

    if cfg.remove_specks_px > 0:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), connectivity=8
        )
        if count > 2:
            keep = np.zeros_like(mask)
            for label in range(1, count):
                if stats[label, cv2.CC_STAT_AREA] > cfg.remove_specks_px:
                    keep |= labels == label
            if keep.any():
                mask = keep

    return mask
