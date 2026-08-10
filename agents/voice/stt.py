"""
Speech-to-text with a fallback chain.

Agent 5 used to be Groq's Whisper and nothing else. When that key turned out to
be invalid the whole voice loop returned an empty transcript, and the worker was
told "I did not catch that" — which is a lie about what happened. The worker
adjusts their voice and tries again, and it fails again, because the problem was
never the audio.

So: try each backend in turn, and report which one answered and why the others
did not.

    groq      whisper-large-v3-turbo. Fastest when the key is valid.
    gemini    gemini-flash-latest with inline audio. Already configured here
              for the VLM and TTS, so it needs no extra credential.

WHY NOT DECIDE UP FRONT. A key's validity cannot be known without spending a
request, so `available()` reports "configured", never "working". A status
endpoint that promises a backend works because an env var is non-empty is how a
401 turns into a silent empty transcript at the worst possible moment.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Optional

import requests

GEMINI_STT_MODEL = os.getenv("GEMINI_STT_MODEL", "gemini-flash-latest")

# Whisper and Gemini both infer container from the declared type, and the
# recorder on the worker's phone picks whichever it supports — webm on Android,
# mp4 on iOS. Guessing wrong here produces a decode failure that looks exactly
# like silence.
_MIME = {
    "webm": "audio/webm", "mp4": "audio/mp4", "m4a": "audio/mp4",
    "ogg": "audio/ogg", "wav": "audio/wav", "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg", "flac": "audio/flac",
}


@dataclass
class Transcription:
    text: str = ""
    backend: Optional[str] = None
    attempts: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())

    def as_dict(self) -> dict:
        return {"transcript": self.text, "backend": self.backend, "attempts": self.attempts}


def _mime_for(filename: str) -> str:
    return _MIME.get((filename.rsplit(".", 1)[-1] or "").lower(), "audio/webm")


def _via_groq(audio: bytes, filename: str) -> str:
    import groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")

    import io
    buf = io.BytesIO(audio)
    buf.name = filename                      # the SDK infers format from this
    resp = groq.Groq(api_key=key).audio.transcriptions.create(
        model="whisper-large-v3-turbo", file=buf, response_format="text")
    return resp if isinstance(resp, str) else getattr(resp, "text", "")


def _via_gemini(audio: bytes, filename: str) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_STT_MODEL}:generateContent?key={key}")
    payload = {
        "contents": [{
            "parts": [
                # Explicit about wanting only the words: without this it tends to
                # answer the question in the audio instead of transcribing it,
                # which silently turns Agent 5 into an oracle.
                {"text": "Transcribe this audio verbatim. Reply with the spoken "
                         "words only — no commentary, no punctuation notes, and "
                         "do not answer any question you hear."},
                {"inline_data": {"mime_type": _mime_for(filename),
                                 "data": base64.b64encode(audio).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0.0},
    }
    r = requests.post(url, json=payload, timeout=45)
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return " ".join(p.get("text", "") for p in parts).strip()


_BACKENDS = [
    ("groq:whisper-large-v3-turbo", _via_groq),
    (f"gemini:{GEMINI_STT_MODEL}", _via_gemini),
]


def transcribe(audio: bytes, filename: str = "audio.webm") -> Transcription:
    """Transcribe `audio`, trying each configured backend in order."""
    result = Transcription()

    if not audio:
        result.attempts.append({"backend": "-", "error": "no audio bytes"})
        return result

    for name, fn in _BACKENDS:
        try:
            text = (fn(audio, filename) or "").strip()
        except Exception as e:
            # Truncated: an auth error from an SDK can carry a whole response
            # body, and this string is surfaced to the worker's screen.
            result.attempts.append({"backend": name, "error": f"{type(e).__name__}: {e}"[:200]})
            continue

        if text:
            result.text, result.backend = text, name
            result.attempts.append({"backend": name, "ok": True})
            return result

        result.attempts.append({"backend": name, "error": "empty transcript"})

    return result


def status() -> dict:
    """What is CONFIGURED. Validity is unknowable without spending a request."""
    return {
        "backends": [
            {"name": "groq:whisper-large-v3-turbo", "configured": bool(os.getenv("GROQ_API_KEY"))},
            {"name": f"gemini:{GEMINI_STT_MODEL}", "configured": bool(os.getenv("GEMINI_API_KEY"))},
        ],
        "any_configured": bool(os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY")),
        "note": "Reports configuration, not reachability — a key can be present and rejected.",
    }
