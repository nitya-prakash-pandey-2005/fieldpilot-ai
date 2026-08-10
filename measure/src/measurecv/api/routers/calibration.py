"""Calibration endpoints.

Calibration is the highest-leverage thing a user can do for accuracy, so it is
a first-class API surface rather than a CLI-only afterthought: upload target
photos, get intrinsics back, and have them applied to subsequent measurements
in the same session.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from measurecv.api.deps import AppState, enforce_upload_limit, get_state, require_api_key
from measurecv.api.schemas import CalibrationRequest, CalibrationResponse, ScaleRequest
from measurecv.calibration.board import calibrate_from_images
from measurecv.calibration.scale import estimate_scale_correction, known_reference_sizes
from measurecv.core.logging import get_logger
from measurecv.pipeline.sources import decode_image_bytes

log = get_logger(__name__)

router = APIRouter(
    prefix="/v1/calibration", tags=["calibration"], dependencies=[Depends(require_api_key)]
)


@router.post(
    "/intrinsics",
    response_model=CalibrationResponse,
    summary="Calibrate from chessboard or ChArUco images",
)
async def calibrate(
    state: Annotated[AppState, Depends(get_state)],
    files: Annotated[list[UploadFile], File(description="Photos of the calibration target")],
    params: Annotated[str | None, Form(description="JSON-encoded CalibrationRequest")] = None,
    activate: Annotated[bool, Form(description="Use this profile for later requests")] = True,
) -> dict[str, Any]:
    """Run Zhang's calibration on uploaded target images.

    Accuracy notes that materially affect the result:

    * **Measure the printed square size.** Printers scale. Every measurement
      this system produces is proportional to this number.
    * **Vary the board's orientation.** Views that are all fronto-parallel
      leave the focal length and the board distance mathematically
      indistinguishable.
    * **Cover the image corners.** Distortion coefficients are constrained by
      the periphery; without corner coverage they are extrapolating.
    """
    import json

    request = CalibrationRequest()
    if params:
        try:
            request = CalibrationRequest.model_validate(json.loads(params))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid calibration parameters: {exc}",
            ) from exc

    if len(files) < request.min_views:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"need at least {request.min_views} images, received {len(files)}",
        )

    images = []
    names = []
    for index, upload in enumerate(files):
        data = await upload.read()
        enforce_upload_limit(state, len(data), upload.filename or f"view_{index}")
        images.append(decode_image_bytes(data))
        names.append(upload.filename or f"view_{index}")

    result = calibrate_from_images(
        images,
        (request.board_cols, request.board_rows),
        request.square_size_m,
        names=names,
        board_type=request.board_type,
        marker_size_m=request.marker_size_m,
        min_views=request.min_views,
        max_rms_error_px=request.max_rms_error_px,
    )

    if activate:
        state.pipeline.resolver.set_profile(result.intrinsics)

    return {**result.to_dict(), "activated": activate}


@router.get("/profile", summary="Current camera model")
async def get_profile(state: Annotated[AppState, Depends(get_state)]) -> dict[str, Any]:
    """The calibration profile currently in use, if any."""
    profile = state.pipeline.resolver.profile
    if profile is None:
        return {
            "profile": None,
            "message": (
                "no calibration profile loaded; intrinsics will come from EXIF when available, "
                "otherwise from an assumed field of view with ~15% scale uncertainty"
            ),
        }
    return {"profile": profile.to_dict()}


@router.post("/scale", summary="Refine metric scale with a known reference object")
async def set_scale(
    state: Annotated[AppState, Depends(get_state)], request: ScaleRequest
) -> dict[str, Any]:
    """Fit a multiplicative depth-scale correction from known lengths.

    Measure an object of known size with this system, send both the measured
    and true values, and the residual scale bias is cancelled for all
    subsequent requests. Because every length is homogeneous of degree one in
    depth, a single factor corrects lengths, areas (squared) and volumes
    (cubed) consistently.
    """
    correction = estimate_scale_correction(
        request.measured_m, request.truth_m, reference=request.reference
    )
    state.pipeline.set_scale_correction(correction)
    return {
        "correction": correction.to_dict(),
        "message": (
            f"depth scale adjusted by {correction.factor:.4f} "
            f"(+/-{correction.sigma:.4f}); applied to subsequent measurements"
        ),
    }


@router.delete("/scale", summary="Remove the scale correction")
async def clear_scale(state: Annotated[AppState, Depends(get_state)]) -> dict[str, str]:
    state.pipeline.set_scale_correction(None)
    return {"message": "scale correction cleared"}


@router.get("/references", summary="Built-in reference object dimensions")
async def references() -> dict[str, Any]:
    """Standard objects usable for scale refinement, longest dimension in metres."""
    return {
        "references_m": known_reference_sizes(),
        "note": "ISO/IEC 7810 ID-1 cards and ISO 216 paper sizes are manufactured to tight "
        "tolerances, which makes them good references; printed targets are only as accurate "
        "as the printer.",
    }
