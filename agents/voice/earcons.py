"""
Earcon System — FieldPilot AI
--------------------------------
Distinct short audio cues per hazard category, played immediately before
the spoken TTS alert — per Master Execution Plan Day 7: "distinct short
audio patterns per hazard category". Pure-stdlib synthesized tones (no
licensed audio assets, no extra pip dependencies beyond what's already
used) so they're generated deterministically and are trivially
regeneratable/tunable.

Each category is built from a distinct frequency/rhythm pattern so a
worker can identify the hazard type by sound alone, without looking at a
screen — the whole point of an audio-only device like the Wayfarer Gen 2.
"""

import math
import os
import struct
import wave
from enum import Enum

SAMPLE_RATE = 22050
_EARCON_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "earcons")


class HazardCategory(str, Enum):
    FALL = "fall"
    STRUCK_BY = "struck_by"
    PPE_VIOLATION = "ppe_violation"
    ESCALATED_ATTENTION = "escalated_attention"
    VERSION_MISMATCH = "version_mismatch"
    PASS = "pass"


# (frequency_hz, duration_ms, gap_ms) tuples per beep, per category —
# distinguishable by pitch, rhythm, and beep count, not just volume.
_PATTERNS: dict[HazardCategory, list[tuple[float, int, int]]] = {
    # Most urgent — fast, high-pitched triple beep (like a smoke alarm)
    HazardCategory.FALL: [(1200, 120, 60), (1200, 120, 60), (1200, 120, 0)],
    # Alternating low/high — mimics a vehicle back-up alarm (already a
    # learned "heavy equipment nearby" sound in most workers' experience)
    HazardCategory.STRUCK_BY: [(420, 150, 40), (950, 150, 40), (420, 150, 40), (950, 150, 0)],
    # Single flat medium beep — a routine compliance flag, not an emergency
    HazardCategory.PPE_VIOLATION: [(800, 250, 0)],
    # Rising sweep — "this has been waiting for you", approximated as steps
    HazardCategory.ESCALATED_ATTENTION: [(500, 90, 20), (700, 90, 20), (900, 90, 20), (1100, 120, 0)],
    # Two low, deliberate beeps — "stop and check", distinct from PPE's single beep
    HazardCategory.VERSION_MISMATCH: [(320, 200, 100), (320, 200, 0)],
    # Short pleasant chime — confirms compliance, not a hazard
    HazardCategory.PASS: [(660, 90, 30), (990, 140, 0)],
}


def _synthesize_tone(freq: float, duration_ms: int, volume: float = 0.5) -> bytes:
    n_samples = int(SAMPLE_RATE * duration_ms / 1000)
    frames = bytearray()
    fade = max(1, int(n_samples * 0.08))  # short fade in/out to avoid clicks
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        amp = volume
        if i < fade:
            amp *= i / fade
        elif i > n_samples - fade:
            amp *= (n_samples - i) / fade
        sample = int(amp * 32767 * math.sin(2 * math.pi * freq * t))
        frames += struct.pack("<h", sample)
    return bytes(frames)


def _synthesize_silence(duration_ms: int) -> bytes:
    n_samples = int(SAMPLE_RATE * duration_ms / 1000)
    return b"\x00\x00" * n_samples


def _generate_wav(category: HazardCategory, path: str):
    pattern = _PATTERNS[category]
    pcm = bytearray()
    for freq, duration_ms, gap_ms in pattern:
        pcm += _synthesize_tone(freq, duration_ms)
        if gap_ms:
            pcm += _synthesize_silence(gap_ms)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(bytes(pcm))


def ensure_earcons_generated() -> dict[str, str]:
    """Generate (once, cached to disk) all earcon WAV files. Returns {category: path}."""
    os.makedirs(_EARCON_DIR, exist_ok=True)
    paths = {}
    for category in HazardCategory:
        path = os.path.join(_EARCON_DIR, f"{category.value}.wav")
        if not os.path.exists(path):
            _generate_wav(category, path)
        paths[category.value] = path
    return paths


def play_earcon(category: HazardCategory) -> bool:
    """
    Play the earcon for `category` synchronously (blocks for the clip's
    duration, same as the TTS call it precedes). Uses stdlib `winsound` on
    Windows; silently no-ops (returns False) on other platforms or if audio
    output is unavailable — never raises, matching the "log and continue"
    pattern the rest of the alert pipeline uses.
    """
    paths = ensure_earcons_generated()
    path = paths.get(category.value if isinstance(category, HazardCategory) else category)
    if not path:
        return False
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    generated = ensure_earcons_generated()
    print("Generated earcons:")
    for name, path in generated.items():
        print(f"  {name}: {path}")
