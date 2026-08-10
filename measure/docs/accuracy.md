# Accuracy: where the error comes from and what to do about it

This document is the reasoning behind the numbers. If you only read one
section, read [The error budget](#the-error-budget) — it explains why some
errors shrink when you collect more data and others never will.

---

## The error budget

Back-projection is the whole game:

```
X = (u − cx) · Z / fx
Y = (v − cy) · Z / fy
Z = Z
```

Differentiating gives four error sources that behave *differently* and must not
be pooled:

| Source | Affects | Character | Shrinks with more data? |
|---|---|---|---|
| Metric scale bias (depth model) | all three axes | systematic | **no** |
| Focal-length error (calibration) | lateral (X, Y) only | systematic | **no** |
| Per-pixel depth noise | mainly axial (Z) extent | random | yes, as `√n_eff` |
| Mask/edge localisation | lateral extents | random | yes, as `√n_eff` |

### Why systematic terms set the floor

A 5% scale bias applied to a million pixels is still a 5% bias. Averaging
cannot help, because every sample is wrong in the same direction by the same
factor. This is why:

- More pixels do not fix an uncalibrated camera.
- More *frames* do not either — `TemporalSmoother` explicitly floors the fused
  sigma at the systematic level rather than letting it decay as `1/√n`. Without
  that floor, watching a static object for ten minutes would report a
  millimetre-precision wrong answer.
- The only fixes are **calibration** and a **reference object**.

### Why `n_eff = √n` and not `n`

Textbook averaging assumes independent samples. Monocular depth error is
strongly spatially correlated — neighbouring pixels are wrong together, with
correlation lengths of tens of pixels. Treating a 100 000-pixel mask as 100 000
independent samples would understate uncertainty by roughly 300×. `√n` is
deliberately conservative and matches the empirical observation that doubling
an object's pixel count improves repeatability, but far less than `1/√2`.

### Why axial extents are worse than lateral ones

An extent along the line of sight is a *difference of two depth estimates*, so
it inherits depth noise directly. An extent across the image is
`Δu · Z / f`, which inherits the focal error and pixel localisation instead.
`extent_uncertainty` splits an axis into axial and lateral components by
projecting onto the view direction, so an object measured across the frame
correctly reports a tighter error bar than the same object measured in depth.

### Why volume error is 3× not 1.7×

Volume is a product of three lengths that all ride on the *same* depth scale.
Correlated errors add **linearly**:

```
σ_V/V = 3 · σ_scale      (correlated)
      ≈ 1.73 · σ_scale   (if you wrongly assume independence)
```

A 5% scale error is a **15%** volume error. `product_uncertainty` takes a
`shared_relative` argument precisely to get this right.

---

## Systematic biases that are corrected

These are errors the system *removes* rather than merely reports.

### Boundary shrinkage (was 6.9%, now 0.4%)

Depth networks smooth across silhouettes, so mask-edge pixels carry blended
foreground/background depth. Those pixels sit at the object's outline, so they
land at the extremes of every principal axis and corrupt extent estimates far
more than their count suggests. Erosion and depth-edge suppression remove them
— and shrink the object by a few pixels per side.

The shrinkage is **knowable**, so it is measured and added back:

1. Distance-transform the original mask.
2. The 1st percentile of that field over the *retained* pixels is the
   equivalent erosion radius `r`.
3. Lateral extents gain `2 · (r − 0.5) · Z / f`.

The half-pixel converts between "outermost retained pixel *centre*" and the
true silhouette *edge*. The formulation covers every spatial filter
automatically — including the border-shaving that the k-NN outlier filter
performs on planar surfaces — with no per-filter bookkeeping.

Interior holes sit at large distance-transform values and so leave the low tail
untouched, which is why a genuine hole is not mistaken for boundary movement.

> **Validated:** a rendered 500 mm plate measured **465 mm** raw and **498 mm**
> compensated.

### Percentile trim bias (2% on every dimension)

Using the 1st/99th percentiles instead of min/max resists outliers. But for
samples spread uniformly along an axis — exactly what a filled silhouette gives
— the 1st percentile sits 1% in from the true edge, so the trimmed range
under-measures by 2%.

The relation is invertible: for a uniform distribution the trimmed range is
`(b − a)(1 − 2p/100)`, so dividing by that factor recovers the full extent.
Bounds are expanded symmetrically about the trimmed midpoint, keeping the box
centre correct. Outlier resistance is unaffected — the correction is a fixed
1.02× at default settings, not something that tracks the outlier.

### Convex-hull inflation

A hull is defined entirely by its most extreme points, making raw hull volume
the least robust statistic in the system: sub-percent noise inflates it ~10%,
because noise pushes the surface outward on every face at once and volume goes
as the cube. Hulls are therefore computed on the trimmed core, trimmed **in the
object's own frame** (using the fitted box axes) so real corners survive while
noise does not.

---

## Method selection

### Ground-aligned vs. free PCA boxes

From one viewpoint you see at most three faces of an object. The principal axes
of that *visible surface* are not the object's axes — they tilt toward whatever
happens to be visible. A free PCA box is therefore systematically wrong on
partially observed objects.

A support plane fixes one axis **exactly** and reduces the problem to a
minimum-area rectangle in the plane, which rotating calipers solves optimally
(the optimal rectangle always has a side collinear with a hull edge — Toussaint).
Height becomes "distance above the floor", which needs only the object's top to
be visible.

RANSAC uses a **gravity prior** (default 35°) so it cannot latch onto a wall.
This matters: walls are often larger in a point cloud than the floor, and
without the prior the fit prefers them — putting every height measurement on
the wrong datum.

### Volume models

| Model | Assumption | Best for | Fails on |
|---|---|---|---|
| `extrusion` | footprint swept to the floor | anything on a surface | overhangs |
| `hull` | convex closure onto the plane | irregular shapes | concavities (bowls) |
| `obb` | filled box | boxes, crates | rounded objects (+91%) |
| `ellipsoid` | inscribed ellipsoid | fruit, produce, livestock | boxes (−48%) |

`auto` prefers `extrusion` when a plane exists, then `hull`, then `obb`.
All models are computed and returned in `extras.volume_models_m3`, and their
**disagreement is folded into the reported sigma** — a large spread means the
shape assumptions are doing more work than the measurement is.

---

## Confidence vs. sigma

They answer different questions and both matter.

- **`sigma`** — how wide is the error bar, *assuming the method applies*.
- **`confidence`** — does the method apply at all.

Confidence is a weighted **geometric** mean, not an average, because the factors
are conjunctive: any one approaching zero should drag the whole score down.
Inputs are detection score, mask IoU and stability, filter retention, sample
sufficiency, box conditioning, depth coverage, and calibration provenance.

Truncation is handled separately as a **hard cap at 0.4**, not as another factor.
Part of the object is outside the image, so the reported extent is a lower bound
no matter how good everything else is. Treating it as a graded factor let a
pristine measurement of a clipped object still score 0.79 — which is a number a
caller would reasonably trust.

---

## Practical accuracy

Rough expectations for a well-lit scene, object 1–5 m away, occupying >5% of the
frame:

| Setup | Lateral dimensions | Axial dimension | Volume |
|---|---|---|---|
| Calibrated + reference object | 1–2% | 3–5% | 5–12% |
| Calibrated | 2–4% | 4–7% | 8–18% |
| EXIF intrinsics | 5–8% | 7–10% | 15–30% |
| Assumed FOV | 15–20% | 15–25% | 45–70% |

These are dominated by the systematic terms, which is the whole point: the
calibration row you are on matters more than any processing choice below it.

Degrading conditions — small objects (<2% of frame), heavy occlusion, reflective
or transparent surfaces, very low light, motion blur — show up as lower
`confidence` and explicit `warnings` rather than as silently worse numbers.

---

## Verifying accuracy yourself

```bash
# 1. Calibrate
measurecv calibrate ./board_photos --board 9x6 --square-size 0.025 -o camera.json

# 2. Measure an object of known size
measurecv measure ruler_scene.jpg --calibration camera.json --output result.json

# 3. Feed the truth back as a scale correction
curl -X POST localhost:8000/v1/calibration/scale \
  -H 'Content-Type: application/json' \
  -d '{"measured_m": [0.312], "truth_m": [0.300], "reference": "ruler"}'
```

Measure the **printed** calibration square rather than trusting the nominal
size — printers scale, and every measurement the system produces is directly
proportional to that number.
