# FieldPilot AI — Model Training & Fine-Tuning Plan

**Audience:** you, with a GPU available for 2–3 continuous days.
**Goal:** replace every stock/heuristic model in the repo with weights actually trained on construction data, so the numbers on pitch-deck slides 05 and 07 are backed by a real evaluation run rather than a claim.

Read §0 first — it tells you what to launch on the GPU *immediately*, because two of these jobs are the critical path and everything else can happen while they run.

---

## 0. TL;DR — what to run, in what order

| # | Job | GPU time | Blocks what | Priority |
|---|---|---|---|---|
| **T1** | **Construction detector** — YOLO11m-seg fine-tune, unified 28-class taxonomy | 10–16 h | Agent 1, Agent 2, the whole live demo | 🔴 **START FIRST** |
| **T2** | **Rebar keypoint/spacing model** — YOLO11n-pose retargeted to rebar intersections | 4–6 h | Agent 2's headline measurement | 🔴 **START SECOND** |
| **T3** | **Whisper-small LoRA** — construction jargon + Indian/accented English + site noise | 4–8 h | Agent voice input in a noisy demo room | 🟠 High |
| **T4** | **Qwen2.5-VL-7B LoRA** — deviation image → spec-cited verdict | 12–20 h | Agent 5 compliance reasoning quality | 🟠 High |
| **T5** | **BGE-small embedding fine-tune** — construction spec/RFI retrieval | 1–2 h | Agent 7 RAG citation accuracy | 🟡 Medium |
| **T6** | **Predictive-RFI gradient-boosted model** — tabular + embedding features | < 1 h (CPU ok) | Agent 6 (currently a mock blob) | 🟡 Medium |
| **T7** | **Edge export** — ONNX → INT8 → TensorRT for T1/T2 | 1 h | Offline/NPU story, phone relay | 🟢 After T1/T2 |

**Suggested 3-day wall clock on a single 24GB GPU (RTX 4090 / A5000 / L4):**

```
Day 1  00:00 → 02:00   T0  dataset download + harmonization (CPU-bound, no GPU)
Day 1  02:00 → 18:00   T1  detector fine-tune            (GPU busy)
Day 1  18:00 → 24:00   T2  rebar keypoint fine-tune      (GPU busy)
Day 2  00:00 → 08:00   T3  Whisper LoRA                  (GPU busy)
Day 2  08:00 → 28:00   T4  Qwen2.5-VL LoRA               (GPU busy)  ← longest
Day 3  04:00 → 06:00   T5 + T6 + T7                      (GPU light)
Day 3  06:00 → 08:00   evaluation + baseline comparison + weight drop-in
```

If you have **2 GPUs**, run T1/T2 on GPU0 and T3/T4 on GPU1 and you finish in ~26 hours.

If you only have **Colab/Kaggle free tier** (T4-class GPU, 12–16GB, session limits): do T1 with `yolo11s-seg` instead of `yolo11m-seg`, skip T4 (keep Gemini VLM via API — it is genuinely good and costs you nothing in GPU time), and everything else fits.

---

## 1. Environment (run once on the training box)

```bash
# CUDA 12.1 build — adjust for your driver
pip install torch==2.5.1 torchvision --index-url https://download.pytorch.org/whl/cu121
pip install ultralytics==8.3.* transformers datasets accelerate peft bitsandbytes
pip install roboflow supervision albumentations
pip install sentence-transformers evaluate jiwer soundfile librosa audiomentations
pip install lightgbm scikit-learn pandas pyarrow
pip install qwen-vl-utils          # only if running T4
pip install onnx onnxruntime-gpu onnxslim
```

Verify:
```bash
python -c "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

> **Note on this repo's dev machine:** it currently has `torch 2.13.0+cpu` and no CUDA. Do **not** train here. Train on the GPU box, then copy the resulting `.pt`/`.onnx`/adapter folders back into `models/weights/` — §8 covers the drop-in.

---

## 2. T0 — Datasets: what to download and how they merge

### 2.1 The datasets

All of these are open and free. Counts are approximate — verify after download; the prepare script prints exact numbers.

| ID | Dataset | Approx. images | What it gives us | Source |
|---|---|---|---|---|
| `D1` | **Construction Site Safety (css-data)** | ~2,800 | Hardhat / NO-Hardhat / Vest / NO-Vest / Mask / Person / Cone / machinery / vehicle | Roboflow Universe |
| `D2` | **SH17** (Safety Helmet, 17 classes) | ~8,100 | Fine-grained PPE: helmet, glasses, gloves, shoes, vest, face-mask, ear-muffs, tools | Kaggle / HF |
| `D3` | **MOCS** (Moving Objects in Construction Sites) | ~41,000 | Heavy equipment + workers in real site scenes: excavator, loader, dozer, roller, crane, truck, concrete mixer | MOCS project page |
| `D4` | **ACID** (Alberta Construction Image Dataset) | ~10,000 | Heavy equipment, different geography/weather than MOCS | ACID project page |
| `D5` | **Rebar detection / counting sets** | ~1,500 | Rebar ends, rebar grids — the primary Agent 2 use case | Roboflow Universe (several) |
| `D6` | **CHV** (Colour Helmet & Vest) | ~1,300 | Coloured-helmet variants (role-coded helmets, common on Indian sites) | GitHub |
| `D7` | **Concrete Crack / SDNET2018** | ~56,000 crops | Defect classification head (optional, T1b) | Mendeley / Kaggle |
| `D8` | **Scaffold & formwork sets** | ~800 | Formwork, scaffold, guardrail, open edge | Roboflow Universe |

**Detection training total after merge and dedup: ~52,000 images** — which is what backs the deck's "50,000+ annotated images" line. Keep that number honest by reading it off the prepare script's output, not off this table.

### 2.2 Unified taxonomy — `FieldPilot-28`

Every source dataset uses different class names. The prepare script maps them all into one 28-class space. **This taxonomy is the contract** between training and the runtime code — if you change it, you must change `agents/vision/*` to match.

```
# People & PPE (0–11)
 0  person
 1  hardhat
 2  no_hardhat
 3  safety_vest
 4  no_safety_vest
 5  gloves
 6  no_gloves
 7  safety_glasses
 8  safety_boots
 9  face_mask
10  harness
11  no_harness

# Heavy equipment (12–19)  — struck-by hazard sources
12  excavator
13  loader
14  dozer
15  crane
16  truck
17  forklift
18  roller
19  concrete_mixer

# Structural / MEP assets (20–25) — the assets Agent 2 measures
20  rebar
21  formwork
22  scaffold
23  conduit
24  pipe
25  cable_tray

# Site hazard context (26–27)
26  safety_cone
27  guardrail
```

Full source→unified mapping lives in `models/training/taxonomy.yaml`. Classes with fewer than ~200 instances after merge get logged as **under-represented** — expect `no_harness`, `no_gloves`, and `cable_tray` to land there. Options for those: (a) accept low recall and say so in the eval table, (b) oversample + heavy augmentation, (c) drop the class. Do **not** quietly leave them in and quote a global mAP that hides them.

### 2.3 Splits

- **train / val / test = 70 / 15 / 15**, split **by source scene**, not by random image. MOCS and ACID contain many near-duplicate frames from the same video; a random split leaks and inflates mAP by 5–10 points.
- Hold out `D5` (rebar) test split entirely for the Agent 2 measurement evaluation in §4.

### 2.4 Run it

```bash
export ROBOFLOW_API_KEY=...        # free account
python models/training/prepare_datasets.py --out data/training --datasets D1,D2,D3,D4,D5,D6,D8
```

Outputs `data/training/fieldpilot28/{train,val,test}/{images,labels}` plus `fieldpilot28.yaml` for Ultralytics, and prints the per-class instance histogram you will quote in the deck.

---

## 3. T1 — Construction detector (the important one)

**Base model:** `yolo11m-seg.pt` (segmentation, because Agent 2 needs masks not just boxes to measure rebar edges).
**Why not YOLOv9/RT-DETR as the deck says:** YOLO11-seg gives us detection *and* instance masks in one pass, and Ultralytics' export path to ONNX/TensorRT is what the edge story depends on. Update slide 05 to say YOLO11-seg — it is a strictly newer model than YOLOv9, so this is an upgrade, not a walk-back. Keep RT-DETR listed as the evaluated alternative (§3.4).

```bash
python models/training/train_detector.py \
  --data data/training/fieldpilot28/fieldpilot28.yaml \
  --model yolo11m-seg.pt \
  --epochs 120 --imgsz 960 --batch 16 \
  --name fieldpilot28_v1
```

**Key hyperparameters and why:**

| Setting | Value | Reason |
|---|---|---|
| `imgsz` | 960 | Rebar bars and conduit are thin structures; 640 loses them. This is the single biggest accuracy lever. |
| `epochs` | 120 with `patience=25` | Merged multi-source data converges slower than a single clean set |
| `batch` | 16 @ 24GB, 8 @ 16GB | Drop `imgsz` to 800 before dropping batch below 8 |
| `mosaic` | 1.0, disabled for last 15 epochs (`close_mosaic=15`) | Mosaic helps small objects but distorts the final calibration |
| `copy_paste` | 0.3 | Cheap way to boost the under-represented PPE-negative classes |
| `degrees` | 10 | Glasses footage tilts; site photos don't rotate much beyond that |
| `hsv_v` | 0.5 | Sites go from blazing sun to dark basement — brightness robustness matters more than hue |
| `cos_lr` | true | Stabler final epochs on a noisy merged dataset |

**Target metrics** (these are what you put on the slide, replacing the current unsourced 94.3%):

| Metric | Minimum acceptable | Good | Notes |
|---|---|---|---|
| mAP50 (all 28) | 0.72 | 0.82 | Dragged down by under-represented classes |
| mAP50 (PPE subset: 1–9) | 0.85 | 0.92 | This is the safety-critical subset |
| mAP50 (equipment: 12–19) | 0.80 | 0.90 | MOCS/ACID are large and clean |
| mAP50 (structural: 20–25) | 0.55 | 0.70 | Least data — be honest about this one |
| mAP50-95 (all) | 0.48 | 0.60 | |

**If mAP is below the minimum:** almost always a taxonomy-merge bug, not a training problem. Check the prepare script's histogram for a class with 20 instances, and check that `no_hardhat` from D1 didn't get merged into D2's `head` (they mean different things — D2's `head` is a visible head *regardless* of helmet).

### 3.4 Optional comparison run (for the deck's credibility)

```bash
python models/training/train_detector.py --model rtdetr-l.pt --epochs 80 --name fieldpilot28_rtdetr
```
Run this only if you have spare GPU. A one-row comparison table ("we evaluated RT-DETR-L; YOLO11m-seg won on mAP50 at 3.1× the FPS") is worth more to judges than either number alone.

---

## 4. T2 — Rebar spacing model (Agent 2's headline)

This is the one that makes *"rebar spacing 190mm, spec 150mm ±10mm — STOP WORK"* real instead of scripted.

**Approach:** treat rebar-grid intersections as **keypoints**. A pose model finds the lattice nodes; spacing is then the median nearest-neighbour distance along each axis, converted to millimetres by the ArUco/reference scale factor from `agents/measurement/`.

Why keypoints instead of boxes: bounding boxes on parallel bars overlap heavily and NMS destroys the regular grid you need. Intersections are unambiguous point targets.

**Base model:** `yolo11n-pose.pt` (already in `models/weights/`) retargeted to a single class `rebar_grid` with a variable-count keypoint head — or, simpler and what the script does by default, a **`yolo11s` detector on rebar intersections as tiny boxes** whose centres become the lattice points. The detector variant trains faster and is more robust to partially-occluded grids; use it unless you have time to label true keypoints.

```bash
python models/training/train_rebar_spacing.py \
  --data data/training/rebar/rebar.yaml \
  --epochs 150 --imgsz 1280 --batch 8 \
  --name rebar_lattice_v1
```

`imgsz 1280` here — intersections are small and this model only has to handle one class, so spend the resolution on it.

**Evaluation is different for this model.** mAP is not the metric that matters; **millimetre error against ground truth** is. The eval script measures spacing on the held-out D5 test split against tape-measure ground truth:

```bash
python models/training/eval_measurement.py --weights runs/rebar_lattice_v1/weights/best.pt
```

| Metric | Target | Deck claim it supports |
|---|---|---|
| Mean absolute spacing error | ≤ 5 mm at 1.5 m standoff with ArUco | "±5% measurement accuracy" (system_prompt §13.1) |
| 95th-percentile error | ≤ 12 mm | |
| Detection rate on visible grids | ≥ 90% | |

**You need ground truth for this.** Cheapest path: print an ArUco marker (§4.1), lay it beside any rebar grid, tape-measure 20 real spacings, photograph each from 3 distances. 60 photos, one afternoon, and it turns your accuracy claim into a measured result. **Do this before the demo video** — it's the highest-credibility-per-hour task in this entire document.

### 4.1 ArUco marker for scale

Print `DICT_4X4_50` id=0 at exactly **100 mm × 100 mm** (the size `agents/measurement/estimator.py` assumes). Mount it on rigid card — a curled paper marker is the biggest source of scale error. Generate with:

```bash
python models/training/make_aruco.py --id 0 --size-mm 100 --out data/aruco_100mm.png
```

---

## 5. T3 — Whisper LoRA for construction voice

Groq's hosted `whisper-large-v3-turbo` (what the repo uses today) is excellent in a quiet room and mediocre with a compressor running. A fine-tuned local `whisper-small` beats it on jargon and gives you an offline path.

**Training data — you assemble this, it doesn't exist off the shelf:**

1. **Jargon corpus (you write this):** ~300 utterances of real construction phrasing — *"what's the lap splice length at column C4"*, *"is this rebar spacing to spec"*, *"drawing S-101 revision five"*, *"who approved the east wall conduit routing"*. Include your team's actual demo phrases.
2. **Synthesize speech** for each with 5–8 different TTS voices (varying Indian, British, American accents) → ~2,000 clips.
3. **Augment with real site noise:** MUSAN + freesound construction recordings (angle grinder, concrete mixer, hammer drill, generator) at SNR 0–15 dB → ~8,000 clips.
4. **Record ~200 real clips** of your own team saying the demo phrases with the room fan on. Small but disproportionately valuable — this is the actual demo distribution.

```bash
python models/training/build_voice_dataset.py --jargon data/voice/jargon.txt --out data/training/voice
python models/training/train_whisper_lora.py --base openai/whisper-small --data data/training/voice --epochs 3
```

| Metric | Baseline (whisper-small zero-shot) | Target after LoRA |
|---|---|---|
| WER, clean | ~12% | ≤ 8% |
| WER, 5 dB site noise | ~34% | ≤ 18% |
| Jargon-term recall (*"lap splice"*, *"RFI"*, *"rebar"*) | ~55% | ≥ 90% |

Jargon-term recall is the metric to quote — global WER undersells the improvement because the fine-tune targets specific vocabulary.

---

## 6. T4 — Qwen2.5-VL-7B LoRA for compliance reasoning

**Only do this if T1/T2/T3 are done and you have ≥16 hours of GPU left.** The Gemini VLM path in `agents/vision/vlm_analyzer.py` already works and is genuinely strong. A local VLM buys you: on-prem/air-gapped deployment (a real enterprise objection the deck's NemoClaw line addresses), no per-call cost, and no dependency on venue WiFi during the demo.

**Base:** `Qwen/Qwen2.5-VL-7B-Instruct`, 4-bit QLoRA, r=32, alpha=64, targeting attention + MLP projections. Vision tower frozen.

**Training data — instruction pairs you generate:**

```jsonc
{
  "image": "data/training/vlm/rebar_190mm_zoneA12.jpg",
  "conversations": [
    {"from": "human", "value": "<image>\nZone A12. Spec: rebar spacing 150mm ±10mm per ACI 318-19 §7.7.1. Measured 190mm. Assess."},
    {"from": "gpt", "value": "{\"result\":\"FAIL\",\"severity\":\"CRITICAL\",\"deviation_mm\":40,\"standard_ref\":\"ACI 318-19 §7.7.1\",\"worker_message\":\"Rebar spacing is 190mm. Spec requires 150mm plus or minus 10. Stop work.\",\"engineer_message\":\"...\"}"}
  ]
}
```

Generate ~3,000 of these by pairing detector outputs from T1 with the OSHA/ACI spec text already indexed in Qdrant, and having Gemini draft the target response — then **hand-review 200 of them**. Distilling from Gemini is legitimate and standard; shipping unreviewed synthetic targets is how you get a model that confidently cites a clause that doesn't exist.

```bash
python models/training/build_vlm_dataset.py --out data/training/vlm
python models/training/train_vlm_lora.py --base Qwen/Qwen2.5-VL-7B-Instruct --data data/training/vlm
```

| Metric | Target |
|---|---|
| JSON schema validity | ≥ 99% (hard requirement — the API parses this) |
| PASS/FAIL agreement with `ComplianceEngine` ground truth | ≥ 95% |
| Spec-citation accuracy (clause exists **and** is the right one) | ≥ 90% |
| Hallucinated clause rate | ≤ 2% |

Serve with vLLM: `vllm serve <merged-model> --max-model-len 8192` and point `LLM_BACKEND=vllm` + `LLM_BASE_URL` at it.

---

## 7. T5 / T6 / T7 — the short jobs

### T5 — Embedding fine-tune (1–2 h)
`BAAI/bge-small-en-v1.5` → fine-tune with `MultipleNegativesRankingLoss` on ~1,500 (question, spec-passage) pairs mined from the OSHA PDFs already in `data/` plus your ACI/IS-456 sources.
```bash
python models/training/train_embeddings.py --base BAAI/bge-small-en-v1.5 --data data/training/rag_pairs.jsonl
```
Target: Recall@5 from ~0.71 → ≥ 0.88 on a 200-question held-out set. **Re-index Qdrant after this** or retrieval silently breaks — old vectors and new query embeddings are not in the same space.

### T6 — Predictive RFI model (< 1 h, CPU is fine)
LightGBM binary classifier: *will this zone generate an RFI in the next 14 days?* Features: zone risk score, open-issue count, days-to-scheduled-completion, asset-type one-hot, count of historical RFIs on the same asset type, mean deviation % over last 7 days, drawing revision age. Labels from your seeded/accumulated `resolved_incidents` + `field_issues` history.
```bash
python models/training/train_rfi_predictor.py --out models/weights/rfi_lgbm.txt
```
Target: AUC ≥ 0.75, and — more importantly — **calibrated** probabilities (Brier ≤ 0.18), because the dashboard prints "87% probability" and a judge may well ask what that number means. This replaces `_mock_rfi_prediction()` in `utils/llm_client.py`.

### T7 — Edge export (1 h)
```bash
python models/training/export_edge.py --weights runs/fieldpilot28_v1/weights/best.pt --formats onnx,int8,tensorrt
```
Produces `models/weights/fieldpilot28_v1.onnx`, `..._int8.onnx`, `..._fp16.engine`. INT8 calibration uses 500 images from the val split. Expect ~4× size reduction, ~2.5× speedup, and **≤2 points mAP50 loss** — if you lose more than 4 points, your calibration set isn't representative.

This is what backs the deck's "quantized models run on the phone NPU so safety works in WiFi dead zones" claim, and it's what the mobile app will actually load.

---

## 8. Dropping trained weights back into the app

Copy from the GPU box into `models/weights/`, then set these in `.env`:

```bash
# T1 — replaces stock COCO yolo11n.pt in agents/vision/detector.py
YOLO_MODEL_PATH=models/weights/fieldpilot28_v1.pt
YOLO_TAXONOMY=fieldpilot28              # tells detector.py to use the new class names

# T1 also replaces these two, which become redundant:
#   PPE_MODEL_PATH (api/weights/best.pt, 2-class hardhat)      → classes 1,2 of T1
#   EQUIPMENT_MODEL_PATH (forklift_yolov8n.pt)                 → classes 12–19 of T1
PPE_MODEL_PATH=models/weights/fieldpilot28_v1.pt
EQUIPMENT_MODEL_PATH=models/weights/fieldpilot28_v1.pt

# T2
REBAR_MODEL_PATH=models/weights/rebar_lattice_v1.pt
DEPTH_BACKEND=hybrid                    # aruco when marker visible, depth model otherwise

# T3
WHISPER_BACKEND=local
WHISPER_MODEL_PATH=models/weights/whisper-small-fieldpilot

# T4 (only if trained)
LLM_BACKEND=vllm
LLM_BASE_URL=http://localhost:8000/v1

# T5
EMBEDDING_MODEL_PATH=models/weights/bge-small-fieldpilot

# T6
RFI_MODEL_PATH=models/weights/rfi_lgbm.txt

# T7 — mobile/edge
EDGE_MODEL_PATH=models/weights/fieldpilot28_v1_int8.onnx
```

Then regenerate the baseline so the dashboard's accuracy KPI reads from real numbers:
```bash
python scripts/validate_baseline.py --full
```
This writes a fresh `models/evaluation/baseline_<timestamp>.json`, which `GET /api/v1/health/accuracy` already serves to the Executive Dashboard.

---

## 9. What NOT to train (and why)

Being able to say *"we deliberately didn't train that, here's why"* is a stronger answer to a judge than a half-trained model.

| Thing | Decision | Reason |
|---|---|---|
| **Depth Anything V2** | Use the released **metric** checkpoints zero-shot (`depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf`), do not fine-tune | Fine-tuning metric depth needs LiDAR-paired ground truth you don't have. Zero-shot + ArUco rescaling gets you to the ±5% target. The deck says "synthetic BIM data" for this — that's a Phase-3 item, say so. |
| **SAM2 segmentation** | Use as-is | Zero-shot segmentation is already near-ceiling; fine-tuning it is a research project |
| **Llama-3 8B general reasoning** | Skip entirely | Superseded by T4's VLM, which does text *and* vision. Don't run two LLM fine-tunes. |
| **NeRF / Gaussian Splatting** | Skip for Round 2 | Deck lists it under the 3D site reconstruction story; it's genuinely Phase 3/4 work and doesn't survive a live demo. Show the 3D twin viewer you already have (`ThreeSiteViewer.tsx`) and label it as BIM-overlay, not reconstruction. |
| **PaddleOCR** | Use pretrained, just re-enable it | It's disabled in `agents/version_control/scanner.py` for startup speed, not accuracy. Fix is lazy-loading, not training. |

---

## 10. Evaluation artefacts to have ready for judges

Produce these files and have them open in a tab during the demo. Judges evaluating "quality and efficiency of implementation" respond to a confusion matrix far more than to a claimed percentage.

| Artefact | Produced by | Shows |
|---|---|---|
| `models/evaluation/detector_confusion_matrix.png` | T1 eval | Where the model actually fails |
| `models/evaluation/detector_pr_curve.png` | T1 eval | Per-class precision/recall |
| `models/evaluation/measurement_error_hist.png` | T2 eval | mm error distribution vs tape measure |
| `models/evaluation/whisper_wer_by_snr.png` | T3 eval | WER degradation curve under noise |
| `models/evaluation/baseline_<ts>.json` | `validate_baseline.py` | The numbers the dashboard KPI reads |
| `models/evaluation/class_histogram.png` | T0 prepare | Dataset composition — proves the 50k claim |

---

## 11. Honest risks

- **Structural-asset classes (rebar/formwork/conduit/cable tray) have the least public data.** Expect mAP50 in the 0.55–0.70 band. Mitigation: the ArUco-calibrated measurement path (T2) doesn't need high-mAP *classification* — it needs accurate intersection *localisation*, which is a much easier task on a single class. Present the measurement error, not the detector mAP, for the rebar demo.
- **T4 may not finish in your window.** It's last for a reason. Gemini VLM is a complete fallback and the demo does not degrade without T4.
- **Dataset licences vary.** MOCS and ACID are research-use; Roboflow sets are mostly CC-BY. Fine for a hackathon and for research, but note it if a judge asks about commercialisation — a commercial deployment would need either licensed data or your own labelled set.
- **Don't retrain the day before the demo.** Freeze weights at least 48 hours out. A model that scores 2 points higher but that you haven't run the full E2E test against is a net loss.
