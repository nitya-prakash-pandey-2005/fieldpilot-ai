# Voice Command — Phase 1: Return-Audio Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the new laptop→phone→earbuds audio-return leg works, using a
typed question instead of real speech recognition. This is Phase 1 of 4 from
the spec's staged build order — it deliberately excludes STT and grounding so
the new WebSocket audio path can be validated in isolation.

**Architecture:** Reuse the existing `/v1/stream/ws` WebSocket and its
JSON-command channel (`_handle_command` in
`src/measurecv/api/routers/stream.py`) rather than building a new endpoint.
A new `voice_query` command takes typed text, synthesizes it to speech with
Piper, and sends the audio back as a **binary** WebSocket frame — the server
currently never sends binary to the client, so the client can treat any
binary message as audio with no envelope/tagging needed. The phone-side page
(`src/measurecv/api/static.py`) gets a text input, an "Ask" button, and
playback of the returned audio through the browser's default audio output
(the paired Bluetooth earbuds, once connected — no special JS targeting
needed, that's normal OS-level audio routing).

**Tech Stack:** Piper TTS (invoked via its CLI, not its Python API — see Task
1 rationale), FastAPI WebSocket (existing), vanilla JS (existing page has no
framework).

## Global Constraints

- Response is spoken-only; no on-screen text answer is in scope (per spec).
- This phase runs entirely on the laptop; nothing is cloud-hosted (per spec's
  deployment shape).
- No LLM anywhere in this feature — command/response text is template-driven
  (per spec; not exercised until Phase 2/3, but the TTS wrapper built here
  must not assume any input beyond a plain string).
- Test suite must stay runnable without downloaded models by default, matching
  this project's existing 271-test suite (`README.md`, "Testing" section) —
  new tests that need the real Piper binary/voice model must be
  `pytest.importorskip`-gated, following the existing `api_client` fixture's
  pattern in `tests/conftest.py:137-139`.

---

### Task 1: Piper TTS wrapper

**Files:**
- Create: `src/measurecv/voice/__init__.py`
- Create: `src/measurecv/voice/tts.py`
- Modify: `src/measurecv/core/exceptions.py` (add `VoiceError`, following this
  file's existing convention that every `MeasureCVError` subclass lives here
  — confirmed by inspecting the file: `ConfigurationError`, `ModelLoadError`,
  `CalibrationError`, `DepthEstimationError`, `InsufficientDataError`,
  `DegenerateGeometryError`, `UnsupportedInputError`, `SourceError` are all
  defined in this one module, none in their feature's own file)
- Modify: `pyproject.toml` (add `voice` extra)
- Test: `tests/test_voice.py`

**Interfaces:**
- Produces: `measurecv.voice.tts.synthesize(text: str) -> bytes` — returns a
  complete WAV file's bytes. Raises `measurecv.core.exceptions.VoiceError` if
  the `piper` binary is missing, the voice model isn't downloaded, or
  synthesis fails.

Piper is invoked via its CLI binary (`piper --model <path> --output_file -`
reading text from stdin), not the `piper-tts` Python package's internal API.
Rationale: the CLI contract (stdin text in, WAV bytes out) is Piper's stable,
documented public interface; the Python package's internal class API has
changed across versions and pinning to it would be a fragile dependency for
one function call. This mirrors nothing else in the codebase (there's no
existing subprocess-wrapped model here — RT-DETR/SAM2/Metric3D are all
in-process) so it's called out explicitly rather than presented as an
established pattern.

- [ ] **Step 1: Write the failing test for the missing-binary error path**

```python
# tests/test_voice.py
from __future__ import annotations

import pytest

from measurecv.core.exceptions import MeasureCVError


class TestSynthesize:
    def test_raises_measurecv_error_when_piper_binary_is_missing(self, monkeypatch) -> None:
        from measurecv.voice.tts import synthesize

        monkeypatch.setenv("PATH", "")  # no `piper` reachable anywhere
        with pytest.raises(MeasureCVError, match="piper"):
            synthesize("hello")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_voice.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'measurecv.voice'`
(the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

First, add `VoiceError` to `src/measurecv/core/exceptions.py`, following the
exact style of the existing subclasses (e.g. `CalibrationError` at line 56).
Add it after `SourceError` (the last class in the file) and add it to the
module's `__all__` list (alphabetical, matching the existing ordering):

```python
class VoiceError(MeasureCVError):
    """Speech synthesis or recognition failed (missing binary, model, or
    a failed subprocess call)."""

    status_code = 503
    code = "voice_error"
```

Add `"VoiceError"` to `__all__` in that file, keeping alphabetical order
(between `"UnsupportedInputError"` and the closing bracket, since it sorts
last).

```python
# src/measurecv/voice/__init__.py
"""Voice input/output: speech synthesis and (later phases) recognition."""
```

```python
# src/measurecv/voice/tts.py
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
```

Check `src/measurecv/core/exceptions.py` for the base `MeasureCVError`
signature before writing `VoiceError` — it must match the constructor shape
every other `*Error` subclass in that file uses (single message argument, or
message plus keyword context, whichever the base class defines).

- [ ] **Step 4: Add the `voice` extra to `pyproject.toml`**

Add alongside the existing `onnx` extra (`pyproject.toml:56`):

```toml
voice = ["piper-tts>=1.2"]
```

And update the `all` extra (`pyproject.toml:67`) to include it:

```toml
all = ["measurecv[models,api,onnx,voice,dev]"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_voice.py -v`
Expected: PASS

- [ ] **Step 6: Install piper and the voice model, verify real synthesis manually**

```bash
pip install -e ".[voice]"
python -m piper.download_voices en_US-lessac-medium
python -c "
from measurecv.voice.tts import synthesize
audio = synthesize('The pipe is fifteen centimetres across.')
open('/tmp/test_tts.wav', 'wb').write(audio)
print(len(audio), 'bytes written')
"
```

Play `/tmp/test_tts.wav` and confirm it's audible, intelligible speech.
This step has no automated assertion — it's a manual listening check, and the
plan says so rather than pretending a byte-count check verifies audio
quality.

- [ ] **Step 7: Write the gated real-synthesis test**

```python
# tests/test_voice.py (append to TestSynthesize)
    def test_real_synthesis_produces_a_wav_file(self) -> None:
        pytest.importorskip("piper")
        from measurecv.voice.tts import synthesize, voice_model_path

        if not voice_model_path().is_file():
            pytest.skip("voice model not downloaded; see tts.py docstring")

        audio = synthesize("testing one two three")
        assert audio[:4] == b"RIFF"
        assert len(audio) > 1000
```

- [ ] **Step 8: Run full test file to verify both tests pass/skip correctly**

Run: `pytest tests/test_voice.py -v`
Expected: `test_raises_measurecv_error_when_piper_binary_is_missing` PASSES;
`test_real_synthesis_produces_a_wav_file` PASSES if you did Step 6, SKIPS
otherwise. Neither should FAIL or ERROR.

- [ ] **Step 9: Commit**

```bash
git add src/measurecv/voice/ src/measurecv/core/exceptions.py tests/test_voice.py pyproject.toml
git commit -m "feat(voice): add Piper TTS wrapper"
```

---

### Task 2: `voice_query` WebSocket command and phone-page audio round trip

**Files:**
- Modify: `src/measurecv/api/routers/stream.py:190-221` (`_handle_command`)
- Modify: `src/measurecv/api/static.py` (page HTML/CSS/JS)
- Test: `tests/test_pipeline_api.py` (add near the existing WS tests,
  `tests/test_pipeline_api.py:589-635`)

**Interfaces:**
- Consumes: `measurecv.voice.tts.synthesize(text: str) -> bytes` (Task 1)
- Produces: WS command `{"command": "voice_query", "text": "<question>"}` →
  binary WS frame containing WAV bytes. No new Python-level interface for
  later tasks to consume — Phase 2 will replace the client-typed `text` with
  server-side STT output, but the command shape and server handling stay the
  same.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_api.py — add to the class containing the existing
# websocket tests (same class as test_websocket_control_commands)
    def test_voice_query_returns_synthesized_audio(self, api_client, monkeypatch) -> None:
        def fake_synthesize(text: str) -> bytes:
            assert text == "what is the size of the pipe"
            return b"FAKE_WAV_BYTES"

        monkeypatch.setattr(
            "measurecv.api.routers.stream.synthesize", fake_synthesize
        )
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ws.send_text(json.dumps({
                "command": "voice_query",
                "text": "what is the size of the pipe",
            }))
            audio = ws.receive_bytes()

        assert audio == b"FAKE_WAV_BYTES"

    def test_voice_query_missing_text_is_an_error(self, api_client) -> None:
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ws.send_text(json.dumps({"command": "voice_query"}))
            error = ws.receive_json()
        assert error["type"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_api.py -k voice_query -v`
Expected: FAIL — `_handle_command` has no `voice_query` branch, so the
`fake_synthesize` patch target doesn't even exist yet
(`AttributeError`/`ModuleNotFoundError` depending on where pytest fails
first), and the server currently replies with the existing
`"unknown command: voice_query"` JSON error rather than sending bytes.

- [ ] **Step 3: Implement the command handler**

In `src/measurecv/api/routers/stream.py`, add the import near the top
(`stream.py:30-38`):

```python
from measurecv.voice.tts import VoiceError, synthesize
```

Modify `_handle_command` (`stream.py:190-221`) to add a new branch. The
function currently ends with an `if/elif/else` chain
(`stream.py:206-221`) — insert a new `elif` before the final `else`:

```python
    elif command == "voice_query":
        text = None
        try:
            text = json.loads(text_raw).get("text")
        except json.JSONDecodeError:
            pass
        if not text:
            await websocket.send_json(
                {"type": "error", "message": "voice_query requires a non-empty 'text' field"}
            )
            return
        try:
            audio = await asyncio.to_thread(synthesize, text)
        except VoiceError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            return
        await websocket.send_bytes(audio)
```

This requires renaming the existing `text` parameter of `_handle_command`
(currently the raw message string, `stream.py:193`) since the new branch
needs both the raw string and the parsed field. Rename the parameter to
`text_raw` throughout the function and update its one call site
(`stream.py:123`) to match. The existing `json.loads(text).get("command")`
at `stream.py:201` becomes `json.loads(text_raw).get("command")`, and the
same already-parsed dict can be reused for `.get("text")` instead of
re-parsing — restructure the top of the function to parse once:

```python
async def _handle_command(
    websocket: WebSocket,
    pipeline: MeasurementPipeline,
    text_raw: str,
    processed: int,
    dropped: int,
    started: float,
) -> None:
    import json

    try:
        payload = json.loads(text_raw)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "control messages must be JSON"})
        return
    command = payload.get("command")

    if command == "reset":
        pipeline.reset_state()
        await websocket.send_json({"type": "ack", "command": "reset"})
    elif command == "stats":
        elapsed = max(1e-6, time.time() - started)
        await websocket.send_json(
            {
                "type": "stats",
                "processed": processed,
                "dropped": dropped,
                "fps": round(processed / elapsed, 2),
                "pipeline": pipeline.stats(),
            }
        )
    elif command == "voice_query":
        text = payload.get("text")
        if not text:
            await websocket.send_json(
                {"type": "error", "message": "voice_query requires a non-empty 'text' field"}
            )
            return
        try:
            audio = await asyncio.to_thread(synthesize, text)
        except VoiceError as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            return
        await websocket.send_bytes(audio)
    else:
        await websocket.send_json({"type": "error", "message": f"unknown command: {command}"})
```

This replaces the whole function body (`stream.py:190-221`); the signature's
`text: str` parameter becomes `text_raw: str`. The one call site
(`stream.py:123`, `await _handle_command(websocket, pipeline, text, processed, dropped, started)`)
does not need to change — the caller's local variable is still named `text`
there (it's the raw message string from `message.get("text")` at
`stream.py:121`), only the callee's parameter name changed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_api.py -k voice_query -v`
Expected: PASS

- [ ] **Step 5: Run the full existing WS test suite to check nothing broke**

Run: `pytest tests/test_pipeline_api.py -v`
Expected: all PASS, including the pre-existing
`test_websocket_control_commands` (which exercises `stats`/`reset`/`bogus`
and must still behave identically after the refactor).

- [ ] **Step 6: Add the phone-page UI — text input and Ask button**

In `src/measurecv/api/static.py`, add markup after the existing `<header>`
close and before `<main>` (`static.py:124-126`):

```html
<div style="padding:.6rem 1rem;border-bottom:1px solid var(--line);background:var(--panel);display:flex;gap:.5rem;">
  <input id="voice-text" type="text" placeholder="what is the size of the pipe"
         style="flex:1;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:3px;padding:.4rem .6rem;font:inherit;">
  <button id="ask" disabled>Ask</button>
</div>
```

- [ ] **Step 7: Add the client-side send + binary-audio playback logic**

In the `<script>` block, the `ws.onmessage` handler currently assumes every
message is JSON (`static.py:222-235`). Binary frames arrive as
`ArrayBuffer` (set via `ws.binaryType = "arraybuffer"`,
`static.py:217`), and `JSON.parse` on an `ArrayBuffer` throws, which the
existing `try { msg = JSON.parse(ev.data); } catch (_) { return; }`
(`static.py:224`) already silently swallows — so audio playback needs to be
checked **before** that JSON-parse attempt, not added as a new catch branch.
Replace `ws.onmessage` (`static.py:222-235`):

```javascript
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) { playAudio(ev.data); return; }
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.type === "error") { setStatus("err", msg.message || "error"); inFlight = false; return; }
      if (msg.type !== "measurement") return;

      inFlight = false;
      measured += 1;
      const now = performance.now();
      latency = now - lastAt;
      rate = measured / ((now - fpsStart) / 1000);
      lastScene = msg;
      render(msg);
    };
```

Add the `playAudio` function and the `Ask` button's click handler near the
other functions in the same `<script>` block (after `stop()`,
`static.py:240-247`):

```javascript
  function playAudio(buffer) {
    const blob = new Blob([buffer], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url));
    audio.play().catch((err) => setStatus("err", "audio playback blocked: " + err.name));
  }

  function askQuestion() {
    const text = $("voice-text").value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ command: "voice_query", text }));
  }
```

Wire the button and enable/disable it with connection state, next to the
existing `$("start")`/`$("stop")` listeners (`static.py:355-356`):

```javascript
  $("ask").addEventListener("click", askQuestion);
```

And in `start()`, alongside the existing
`$("start").disabled = true; $("stop").disabled = false;`
(`static.py:237`), add `$("ask").disabled = false;`. In `stop()`, alongside
the existing `$("start").disabled = false; $("stop").disabled = true;`
(`static.py:245`), add `$("ask").disabled = true;`.

- [ ] **Step 8: Update the existing static-content test**

`tests/test_pipeline_api.py` has a test asserting the live page contains
certain tokens (near `test_live_page_warns_about_secure_context`, check the
test immediately above it in the same class for the exact assertion — it
loops over a tuple of required substrings). Add `"voice_query"` to that
tuple so a future edit can't silently drop the new command wiring from the
page without a test noticing.

- [ ] **Step 9: Run the full test file once more**

Run: `pytest tests/test_pipeline_api.py -v`
Expected: all PASS.

- [ ] **Step 10: Manual end-to-end check (this is the actual point of Phase 1)**

This step has no pytest assertion — it's what the whole phase exists to
prove, and it can only be verified by hand:

1. `pip install -e ".[api,voice]"` if not already done; ensure the Piper
   voice model is downloaded (Task 1, Step 6).
2. `measurecv serve` on the laptop.
3. On the phone, connect the Bluetooth earbuds, open
   `http://<laptop-lan-ip>:8000/v1/stream/live` in the phone's browser
   (needs HTTPS/tunnel per the page's own secure-context warning, or use
   the laptop's own browser pointed at `localhost:8000` for a same-machine
   dry run first).
4. Click Start, grant camera access, click Ask with some text typed in.
5. Confirm audio is heard through the earbuds.

Record the actual latency observed (tap Ask → audio starts) — this is the
number the spec's "Open questions/risks" section asked Phase 1 to surface,
and it should inform whether Phase 2's STT model choice needs to be smaller
than `faster-whisper base`.

- [ ] **Step 11: Commit**

```bash
git add src/measurecv/api/routers/stream.py src/measurecv/api/static.py tests/test_pipeline_api.py
git commit -m "feat(voice): add voice_query WS command and phone-page audio round trip"
```

---

## Explicitly out of scope for this plan

Matches the spec's "Explicitly out of scope" section plus the phase
boundary: no STT (Phase 2), no grounding (Phase 3), no earbud
assistant-button trigger (Phase 4), no wake word, no on-screen answer
display, no cloud services. The `text` field in `voice_query` is typed by
hand for this phase; Phase 2's plan will replace the typing with a
transcribed clip without changing the WS command shape.

## Next steps after this plan

Phase 1's manual latency measurement (Task 2, Step 10) should be recorded
before writing Phase 2's plan (STT) — the spec flagged this build order
specifically so real numbers, not assumptions, drive the next phase's model
size choices. Phase 2, 3, and 4 each get their own plan document, written
after the prior phase is done, per the spec's staged build order and its
explicit risk note that the latency target may need revisiting.
