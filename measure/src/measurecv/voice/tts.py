"""Text-to-speech via the Piper CLI.

Piper is invoked as a subprocess rather than through its Python package's
internal API: the CLI's stdin-text-in / stdout-WAV-out contract is Piper's
stable public interface, while the Python class API has changed across
releases. One function call does not justify pinning to the less stable
surface.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from measurecv.core.exceptions import VoiceError
from measurecv.core.logging import get_logger

log = get_logger(__name__)

__all__ = ["synthesize", "voice_model_path"]

#: Small English voice; ~60MB, adequate quality for spoken measurement
#: readouts. Downloaded on first use into the same cache root the rest of
#: the project uses for model weights.
_VOICE_NAME = "en_US-lessac-medium"


def voice_model_path() -> Path:
    """Where the Piper voice model is expected to live.

    Reuses the project's existing cache convention
    (``AppConfig.cache_dir``, ``~/.cache/measurecv`` by default) rather than
    inventing a second cache location.
    """
    cache_root = Path(os.environ.get("MEASURECV_CACHE_DIR", Path.home() / ".cache" / "measurecv"))
    return cache_root / "voices" / f"{_VOICE_NAME}.onnx"


def synthesize(text: str) -> bytes:
    """Synthesize ``text`` to speech, returning complete WAV bytes.

    Raises:
        VoiceError: The ``piper`` binary is not on PATH, the voice model is
            not present, or synthesis fails.
    """
    if not text.strip():
        raise VoiceError("cannot synthesize empty text")

    binary = shutil.which("piper")
    if binary is None:
        raise VoiceError(
            "the 'piper' binary is not on PATH; install it with "
            "`pip install measurecv[voice]` and ensure its console script "
            "is reachable"
        )

    model = voice_model_path()
    if not model.is_file():
        raise VoiceError(
            f"voice model not found at {model}; run "
            f"`python -m piper.download_voices {_VOICE_NAME}` first, or set "
            "MEASURECV_CACHE_DIR to a location that already has it"
        )

    try:
        result = subprocess.run(
            [binary, "--model", str(model), "--output_file", "-"],
            input=text.encode("utf-8"),
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        raise VoiceError(f"piper exited with an error: {exc.stderr.decode(errors='replace')}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VoiceError("piper synthesis timed out after 30s") from exc

    if not result.stdout:
        raise VoiceError("piper produced no audio output")

    log.info("tts_synthesized", chars=len(text), bytes=len(result.stdout))
    return result.stdout
