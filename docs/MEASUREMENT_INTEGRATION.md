# Agent 2 — measurecv integration

`measure/` is a self-contained metrology package (`measurecv`, Apache-2.0) that
now backs half of Agent 2. This document says what it added, what it did not,
and how far the numbers can be trusted.

---

## Why there are two measurement engines, not one

They answer different questions, and neither can answer the other's.

| | `agents/measurement/estimator.py` | `agents/measurement/measurecv_backend.py` |
|---|---|---|
| Question | "How far apart are these rebar?" | "How big is that object, and how far away?" |
| Method | pixels → mm scale, then 2-D geometry | RT-DETR → SAM 2 → Metric3D → 3-D reconstruction |
| Scale from | ArUco homography / reference object / metric depth | camera intrinsics + metric depth + support plane |
| Output | spacing, clearance, length, diameter | L × W × H, volume, standoff distance |
| Best accuracy | ±1–2 mm with an ArUco marker in plane | 1–2% calibrated, ~15% uncalibrated |
| Breaks when | the target is not a repeated planar pattern | the object is not one of RT-DETR's 80 COCO classes |

A single px/mm ratio is valid at exactly one depth and one viewing angle. That
is fine for a rebar mat photographed roughly face-on — and it is why the ArUco
path is still the most accurate thing in the system. It is useless for an object
that extends away from the camera, because the far end is at a different scale
than the near end. That is the gap measurecv fills.

---

## What changed

### 1. `agents/measurement/measurecv_backend.py` (new)

The adapter. Owns the lazily-built `MeasurementPipeline`, converts between the
two systems' conventions, and enforces the refusal contract.

Two conversions matter and are both tested:

- **BGR → RGB.** FieldPilot decodes frames with OpenCV; measurecv expects RGB.
  Getting this backwards does not raise — the detector still finds *something* —
  so it can only be caught by asserting channel order.
- **metres → millimetres, with the error bar.** Construction tolerances are
  written in mm. The conversion carries `sigma`, `relative_error` and the 95%
  interval across; dropping them would turn a value with a stated ±12% into a
  bare number that reads as exact.

### 2. Metric3D became the default depth provider

Rung 3 of the existing calibration ladder (ArUco → reference object → depth →
refuse) now prefers Metric3D over Depth Anything V2.

Both models advertise "metric" depth. The difference is the **canonical camera
transform**: Metric3D predicts in a canonical space with a fixed 1000 px focal
length, and its output must be rescaled by `f_real × resize_scale / 1000` to
become metres. measurecv does this in one audited function. Skip it and the
depth map is smooth, correctly ordered, and wrong by the ratio of your focal
length to 1000 — roughly **40% on a typical phone camera**, with nothing in the
output to indicate a problem.

Selected by `DEPTH_PROVIDER` (`auto` | `measurecv` | `depth_anything`). The
provider that actually ran is reported in every response as
`calibration.depth_provider`, so it is never inferred from environment state at
read time.

Only the depth stage runs on this path — detection and segmentation are skipped,
since the calibration ladder discards the masks. That is ~12 s saved per call on
CPU. Verified to produce depth identical to the full-pipeline path.

### 3. New endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/measurement/objects` | Dimension objects in an uploaded image |
| `POST /api/v1/measurement/objects/frame` | Same, base64 — the live camera path |
| `POST /api/v1/measurement/objects/validate` | Dimension one object and check it against a spec |

### 4. An uncertainty-aware verdict

`/objects/validate` does not compare a point estimate to a threshold. It asks
whether the **95% interval** clears the tolerance boundary:

- interval entirely inside tolerance → `PASS`
- interval entirely outside → `FAIL`, with severity
- **interval straddles a limit → `UNCERTAIN`**, with the interval and a remedy

The third case is the point. A point measurement flips from PASS to FAIL the
instant it crosses a limit, however uncertain it is. Since Agent 5 escalates a
FAIL to STOP WORK, that is how a system halts a site over sensor noise. Measured
behaviour on a real frame:

```
tol 900–1100 mm, CI [922.8, 1404.9] crosses 1100  →  UNCERTAIN
tol 250–350 mm,  CI entirely above                →  FAIL (CRITICAL)
tol 900–1450 mm, CI fully inside                  →  PASS
```

### 5. `DimensioningPanel.tsx`

Renders each dimension's 95% interval as an actual bar rather than a tooltip,
and puts the calibration provenance in a coloured badge at the top. A reader
should not have to hover to discover that the tolerance they care about sits
inside the uncertainty.

---

## Honest accuracy

Read `calibration_source` on every response. It is the single field that says
how far the absolute scale can be trusted:

| Value | Meaning | Scale accuracy |
|---|---|---|
| `calibrated` | Chessboard/target calibration | **1–2%** |
| `exif` | Derived from image metadata | ~5% |
| `provided` | Supplied by the caller | as stated |
| `assumed_fov` | **No calibration** — assumes a 60° FOV | **~15%** |

**Out of the box you get `assumed_fov`.** Five minutes with a printed
chessboard (`POST /v1/calibration/intrinsics` on the measurecv service) takes
this to 1–2%, and it is the largest single accuracy win available — no amount of
processing removes a focal-length error.

Two further caveats the engine reports rather than hides:

- **Volume is an inference, not a measurement.** One viewpoint never sees the
  back of an object. Concave shapes read high.
- **Truncated objects give lower bounds**, flagged with
  `"object touches the frame border"` and capped at 0.4 confidence.

### What it cannot measure

RT-DETR recognises the 80 COCO classes. Rebar mats, formwork, ducting and
scaffolding are **not** among them, so they come back as `no_measurement` rather
than being guessed at. Measuring those needs a detector fine-tuned on
construction imagery; the spacing path (ArUco + line detection) covers rebar
today and is more accurate than a 3-D reconstruction would be anyway.

---

## Guardrails

`measurecv` ships synthetic backends for its offline test suite. They render a
metrically self-consistent fake scene — correct units, sensible magnitudes, a
confidence score — so nothing downstream can distinguish their output from a
real measurement.

**The adapter refuses to load a config that selects them** (`ModelLoadError` at
startup, `available() == False`), rather than serving fabricated numbers. When
the real weights are absent the response is `status: "unavailable"` with a
`remedy` field, and no `objects`.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `MEASURECV_ENABLED` | `1` | `0` hard-disables dimensioning |
| `MEASURECV_CONFIG` | `measure/configs/cpu.yaml` | use `gpu.yaml` on CUDA, `realtime.yaml` for streams |
| `MEASURECV_DEVICE` | from config | `cuda` \| `cpu` |
| `DEPTH_PROVIDER` | `auto` | `auto` \| `measurecv` \| `depth_anything` |

Weights (~500 MB for the CPU preset) download on first use and cache in
`~/.cache`. Nothing is bundled in the repo.

### Performance, measured on this laptop (CPU, Python 3.14, torch 2.13)

| Operation | Time |
|---|---|
| Pipeline construction | 1.2 s (weights load lazily) |
| Full dimensioning pass | ~20–26 s/frame |
| Depth only (calibration ladder) | ~5.6 s warm |

Do **not** shrink `depth.input_size` to speed this up. It looks safe and is not:
Metric3D's priors are resolution-dependent, and halving the input costs up to
**45% depth accuracy** while still producing a perfectly reasonable-looking map.
Use `runtime.depth_every_n_frames` instead.

---

## Tests

```bash
python -m pytest measure/tests -c measure/pyproject.toml   # 294 — the engine
python -m pytest tests/                                    # 40  — FieldPilot, incl. integration
```

`tests/unit/test_measurecv_integration.py` covers the refusal contract, the
synthetic-backend rejection, the unit boundary and the channel-order swap. All
hermetic: no weights, no downloads, no GPU.

> **Note on the hermetic env vars.** `DEPTH_ENABLED` / `MEASURECV_ENABLED` are
> read at module import, so setting them at the top of a test file only works if
> that file is imported before the backend. Any test whose *correctness* depends
> on a provider being absent must stub that provider itself — see
> `test_engine_refuses_when_uncalibrated`.

---

## Licensing

`measurecv` is Apache-2.0. Model weights carry their own: RT-DETR (Apache-2.0),
SAM 2 (Apache-2.0), Metric3D (BSD-2-Clause). All commercial-clean; verify before
shipping. Note this is a cleaner licence position than the Ultralytics YOLO
models used elsewhere in the repo, which are AGPL-3.0.
