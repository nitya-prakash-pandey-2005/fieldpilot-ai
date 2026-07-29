"""
Text-to-Speech — FieldPilot AI (Gemini)
------------------------------------------
Closes the Day-2 voice-loop gap: api/routes/voice.py previously always
returned `"audio_base64": ""` with a comment "Audio handled client-side for
now" — no server-side TTS existed at all. Groq's Whisper STT stays exactly
as-is (fast, already working); only the TTS half is new here.

Uses Gemini's native TTS (generateContent with responseModalities=["AUDIO"]),
which returns raw 16-bit PCM at 24kHz mono — wrapped into a minimal WAV
container here so callers get a normal playable audio/wav file instead of a
headerless PCM blob.
"""

import os
import base64
import struct
from typing import Optional
import requests

GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Kore")
SAMPLE_RATE = 24000


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wrap headerless PCM (what Gemini TTS returns) in a minimal WAV container."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm_bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )
    return header + pcm_bytes


def synthesize_speech(text: str, api_key: Optional[str] = None) -> Optional[str]:
    """
    Synthesize `text` to speech via Gemini TTS.

    Returns a base64-encoded WAV string, or None on failure/missing key —
    callers should treat None exactly like the old empty-string case
    (falls back to client-side TTS), not raise.
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or not text:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_TTS_MODEL}:generateContent?key={key}"
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_TTS_VOICE}}
            },
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        part = data["candidates"][0]["content"]["parts"][0]
        pcm_bytes = base64.b64decode(part["inlineData"]["data"])
        wav_bytes = _pcm_to_wav(pcm_bytes)
        return base64.b64encode(wav_bytes).decode()
    except Exception as e:
        print(f"[TTS] Gemini synthesis failed: {e}")
        return None
