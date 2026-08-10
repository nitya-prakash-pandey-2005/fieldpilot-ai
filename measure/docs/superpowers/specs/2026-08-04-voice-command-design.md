# Voice-command measurement — design

## Purpose

Let a construction-site worker trigger a measurement by voice: press a
trigger, ask "what is the size of the pipe," get a spoken answer back,
hands mostly free. This is a demo build, running on the same laptop used
for the earlier `measurecv` GPU testing in this project, with a phone as
the camera/audio front end.

## Context this builds on

- `measurecv`'s existing pipeline (`src/measurecv/pipeline/pipeline.py`)
  already does detect → segment → depth → measure, but detection is
  hardwired to RT-DETR's 80 COCO classes. Most job-site objects (rebar,
  pipe, lumber, concrete block, etc.) aren't COCO classes, so RT-DETR
  can't find them — this is why the design introduces open-vocabulary
  grounding instead of trying to extend RT-DETR.
- The existing browser live-view page (`src/measurecv/api/static.py`)
  already streams phone camera video to the server over WebSocket with
  `audio: false`. This design extends that page and protocol rather than
  building a new client.
- There is no existing voice/audio infrastructure in the project — this
  is confirmed by search; the only "audio" hit in the codebase is the
  `audio: false` flag in the existing `getUserMedia` call.

## Deployment shape (confirmed with the user)

- Runs on the user's laptop for a demo (not a phone-only or cloud
  deployment).
- The phone streams camera video to the laptop, same as the existing
  live-view page.
- A Bluetooth earphone is paired **to the phone** (not the laptop) — mic
  input and spoken response both go through it, which means audio has to
  travel phone → laptop → phone, not just phone → laptop.
- Response is **spoken only** (no on-screen requirement for this design;
  a laptop-side text/log display is not in scope).
- Trigger is **manual** — a tap on the phone page (primary) or the
  earbuds' built-in assistant button, attempted as best-effort only.
  Browser-level access to a third-party earbud's assistant button is
  inconsistent across phones/OSes and is not guaranteed to work; the tap
  button is the reliable fallback and must work regardless.
- Target latency is "near-instant" (under ~1-2s), which the user chose
  knowingly after being shown the trade-off: on a 6GB laptop GPU already
  running RT-DETR/SAM2/Metric3D-class models, chaining STT → grounding →
  segmentation → depth → measurement → TTS in sequence makes a true
  sub-2s round trip optimistic. First-cut latency is realistically
  2-4s; every model choice below is picked to get as close to the
  target as reasonably possible without redesigning the whole pipeline
  around it.

## Architecture

```
Phone (browser page, extends existing live-view page)
  - camera capture (existing)
  - mic capture (new)
  - trigger button (new; tap-to-talk)
  - plays back received audio through paired earbuds
        │  WebSocket (extends the existing stream protocol)
        ▼
Laptop (FastAPI, extends the existing stream router)
  trigger_start → buffer audio_chunks → trigger_end
        │
        ▼
  STT (faster-whisper tiny/base)
        │  transcript
        ▼
  command parser (rule-based, no LLM)
        │  object phrase, or None
        ▼
  Grounder (new: OWL-ViT-base) — runs against the latest video frame
        │  BoundingBox, or None
        ▼
  existing pipeline stages, unmodified:
    SAM2 box-prompt segmentation → Metric3D depth → measurement engine
        │  SceneMeasurement for the one grounded object
        ▼
  response templater (rule-based, no LLM)
        │  sentence
        ▼
  TTS (Piper, CPU)
        │  audio bytes
        ▼
  voice_response over WebSocket → phone → earbuds
```

## New components

Following the project's existing pattern of narrow interfaces per model
stage (`Detector`, `Segmenter`, `DepthEstimator` in
`src/measurecv/models/`):

- **`measurecv/voice/stt.py`** — wraps `faster-whisper`.
  `transcribe(audio: bytes) -> str`.
- **`measurecv/voice/command.py`** — rule-based parser.
  `parse_command(text: str) -> str | None`. Matches patterns like
  `"what is the size of (the|a) <phrase>"` and returns `<phrase>`, or
  `None` if the utterance doesn't match a recognized shape. No LLM: this
  command shape is narrow enough that a language model would add latency
  and a new failure mode for no accuracy benefit.
- **`measurecv/models/grounding/`** — new `Grounder` interface, parallel
  to the existing model interfaces:
  - `ground(image, phrase: str) -> BoundingBox | None`
  - Real backend: OWL-ViT-base.
  - Synthetic backend: returns a scripted box for a given phrase, for
    testing without weights — same pattern as the existing synthetic
    `Detector`/`Segmenter`/`DepthEstimator`.
- **`measurecv/voice/tts.py`** — wraps Piper.
  `synthesize(text: str) -> bytes` (audio).
- **Orchestration** — extends `src/measurecv/pipeline/live.py` rather
  than creating a parallel pipeline. On a completed voice trigger it
  runs STT → parse → ground → the pipeline's existing
  `_segment`/`_depth`/measurement stages (unchanged) → template →
  TTS.
- **WebSocket protocol additions** — new message types on the existing
  stream endpoint:
  - `trigger_start` / `trigger_end` (phone → laptop, bounds the
    voice-question audio clip; a fixed max duration, e.g. 6s, is
    enforced server-side as a safety cutoff even if `trigger_end` is
    late or lost)
  - `audio_chunk` (phone → laptop, mic audio between start/end)
  - `voice_response` (laptop → phone, synthesized answer audio)
- **Phone page update** (`src/measurecv/api/static.py`) — add mic
  capture (`getUserMedia` audio, currently `false`), the trigger button,
  and playback of received `voice_response` audio through the earbuds.

## Data flow (one interaction)

1. Worker taps the trigger button. Phone sends `trigger_start` and
   begins streaming `audio_chunk` messages.
2. Worker asks "what is the size of the pipe." Worker taps again (or the
   6s safety cutoff fires) to end. Phone sends `trigger_end`.
3. Laptop concatenates the buffered audio and runs STT →
   `"what is the size of the pipe"`.
4. `parse_command` extracts `"pipe"`. If it returns `None`, skip to the
   "didn't understand" error path (step 8).
5. Grounder runs against the latest video frame for `"pipe"`. If it
   returns `None`, skip to the "not found" error path (step 8).
6. The returned box is passed into the **existing, unmodified** SAM2 →
   Metric3D → measurement engine, exactly as a detected object would be.
7. The resulting `SceneMeasurement` for that one object is templated
   into a sentence (e.g. "The pipe is 0.15 meters across and 2.3 meters
   long, 82 percent confidence").
8. **Error paths** (no fabricated numbers, matching this project's
   existing "never silently report a wrong value" principle):
   - Unparseable command → "I didn't catch what to measure."
   - Object not found → "I don't see a `<phrase>` in view."
   - Low confidence / truncated / no support plane → the same warning
     language the rest of the pipeline already produces (e.g.
     truncation lower-bound language), folded into the spoken sentence
     rather than inventing new semantics.
9. TTS synthesizes the response sentence; laptop sends it as
   `voice_response`; phone plays it through the earbuds.

## Error handling summary

| Failure | Response |
|---|---|
| Command doesn't match a recognized question shape | Spoken "didn't catch what to measure," no crash |
| Named object not found in the current frame | Spoken "don't see a `<phrase>` in view," no fabricated number |
| Object found but low confidence / truncated / no ground plane | Same warning language the existing pipeline already produces, spoken instead of only logged |
| Audio never ends (`trigger_end` lost) | Server-side 6s max-duration cutoff forces processing anyway |

## Testing

Matches the project's existing approach (271 tests, deterministic
synthetic backends, no weights or network required for the core suite):

- New `Grounder` interface gets a synthetic backend (scripted box per
  phrase) so the orchestration flow and all error paths are testable
  without STT/TTS/grounding weights or a live phone/earbuds.
- `parse_command` gets direct, deterministic unit tests across the
  recognized phrasing and clearly-unrecognized input.
- STT/grounding/TTS model *accuracy* is not unit-tested — that's model
  quality, not code correctness, and is a manual smoke-test at demo
  time.

## Build order (staged, de-risking the new parts first)

1. Return-audio path only: laptop → phone → earbuds playback, triggered
   by a **typed** question (via the existing phone page, no mic/STT
   yet). Proves the new WebSocket audio-return leg and phone-side
   playback work before adding speech recognition on top.
2. Add STT: replace the typed question with the mic-captured,
   transcribed one.
3. Add grounding: replace a hardcoded/typed object phrase with the real
   `Grounder` call against the live frame.
4. Trigger polish: attempt the Bluetooth earbud assistant-button path;
   keep the tap button as the guaranteed fallback regardless of outcome.

## Explicitly out of scope for this design

- Always-listening wake word (the user chose manual trigger over this).
- On-screen display of the answer (spoken-only was chosen).
- Cloud STT/TTS (local-only was chosen, given the 6GB-laptop-demo
  deployment shape).
- Multi-turn conversation (follow-up questions after an answer) — each
  trigger is a single, independent question.
- Room/open-space measurement — this remains out of scope for the whole
  `measurecv` pipeline, not just this feature (the pipeline is
  detection/grounding-first; it has no mode for bare-space dimensions).

## Open questions / risks carried into implementation

- **Latency target is optimistic.** Sub-2s end-to-end across 5
  sequential model stages on a 6GB GPU is not guaranteed by this design;
  the build order above surfaces real latency numbers early (step 1-2)
  rather than late.
- **Earbud assistant-button access is unverified.** This design treats
  it as best-effort; the tap button is the committed, reliable trigger.
- **VRAM contention** between the Grounder (OWL-ViT-base) and the
  existing detect/segment/depth models sharing the same 6GB card is not
  yet measured — first real test of the full chain will surface whether
  models need to be swapped in/out of VRAM sequentially rather than held
  resident together.
