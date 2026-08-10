# Runbook — clone, train on the lab GPU, push the weights back

For whoever runs training on the shared Jupyter/GPU container. The demo laptop
and the training box are different machines with opposite constraints, and this
is the loop that connects them:

```
laptop  ──git push──▶  branch  ──git pull──▶  GPU container
                                                    │ train
laptop  ◀──git pull──  branch  ◀──git push──────────┘ weights + metrics only
```

**Datasets never travel.** `data/training/` and `runs/` are gitignored on
purpose — they are gigabytes and they are regenerable from
`prepare_datasets.py`. What comes back is `models/weights/*.pt|onnx` and
`models/evaluation/*.json`, which are small and are the actual product.

---

## 0. Before anything — does this machine fit?

```bash
python scripts/check_hardware.py --train
```

It reads **free** VRAM, not card size. On a shared card those are different
numbers and only one of them predicts whether your job survives. It prints the
largest `--batch/--imgsz` that fits and the exact command to run.

---

## 1. Set up (once per container)

```bash
git clone -b dilavesh https://github.com/nitya-prakash-pandey-2005/fieldpilot-ai.git
cd fieldpilot-ai

# torch first, matched to the container's CUDA driver
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install -r models/training/requirements.txt

python -c "import torch;print(torch.__version__, torch.cuda.is_available())"
python scripts/check_hardware.py --train
```

If the container is ephemeral, put the dataset cache somewhere persistent and
symlink it — re-downloading ~50k images on every restart wastes more time than
the training does:

```bash
ln -s /persistent/fieldpilot_downloads data/training/_downloads
```

---

## 2. Datasets (T0)

**Verify D9/D10 before this step.** Their Roboflow coordinates in
`models/training/taxonomy.yaml` were written from class names and have not been
opened by anyone. A wrong version number silently fetches a *different label
set* rather than failing. See `docs/DATASETS.md`.

```bash
export ROBOFLOW_API_KEY=...
python models/training/prepare_datasets.py --out data/training
# default sources: D1,D5,D8,D9,D10  (the Roboflow-fetchable ones)
```

Read the per-class histogram it prints. **That output is the authority** on
image counts — not `docs/TRAINING_PLAN.md`, not `docs/DATASETS.md`, both of
which were written before the data existed. Record the real numbers in
`docs/DATASETS.md` with licences and the download date.

Expect `trench` and `ladder` to be sparse; they are in `known_sparse` for that
reason. Any *other* class landing sparse is a mapping bug, and the script says
so loudly.

---

## 3. Train (T1)

```bash
python models/training/train_detector.py \
    --data data/training/fieldpilot30/fieldpilot30.yaml \
    --model yolo11m-seg.pt \
    --imgsz 960 --batch 4 --epochs 120 \
    --name fieldpilot30_v1
```

`--batch` comes from `check_hardware.py`, not from this file. The script's own
default (16) assumes a 24 GB card and will OOM on a 10–12 GB slice; a VRAM
preflight now says so before the run starts rather than three hours in.

**On a shared card, assume you will be interrupted.** A neighbour allocating
memory mid-run is normal, not exceptional:

```bash
python models/training/train_detector.py --resume runs/detect/fieldpilot30_v1/weights/last.pt
```

Run it under `nohup`/`tmux` so a dropped Jupyter kernel does not kill it.

`imgsz` is the biggest accuracy lever for thin structures like rebar and
conduit — **drop `--batch` before dropping `--imgsz`** (TRAINING_PLAN §3).

---

## 4. Export for the edge (T7)

```bash
python models/training/export_edge.py \
    --weights runs/detect/fieldpilot30_v1/weights/best.pt \
    --formats onnx,int8
```

Publish the INT8 accuracy cost. The repo already did this honestly for the pose
model; an unmeasured export is a claim, not a result.

---

## 5. Push the results back

```bash
cp runs/detect/fieldpilot30_v1/weights/best.pt models/weights/fieldpilot30_v1.pt
cp runs/detect/fieldpilot30_v1/weights/best.onnx models/weights/ 2>/dev/null || true

git add models/weights/ models/evaluation/ docs/DATASETS.md
git commit -m "T1: fieldpilot30_v1 detector — <mAP50> on held-out test split"
git push origin dilavesh
```

Include in the commit message: the held-out mAP50, the date, and the dataset
counts you actually got. A weights file with no provenance is unusable six
weeks later, and Phase 2 §7 requires the number to ship with its split.

**Check nothing huge slipped in** — GitHub hard-rejects any blob over 100 MB,
and a rejected push after a 12-hour job is a bad way to find out:

```bash
git diff --cached --stat
find models/weights -size +90M
```

---

## 6. Back on the laptop

```bash
git pull origin dilavesh
```

Point the runtime at the new weights — no code change, these are env vars:

```bash
YOLO_MODEL_PATH=models/weights/fieldpilot30_v1.pt
PPE_MODEL_PATH=models/weights/fieldpilot30_v1.pt        # T1 subsumes the 2-class model
EQUIPMENT_MODEL_PATH=models/weights/fieldpilot30_v1.pt  # and the forklift model
EDGE_MODEL_PATH=models/weights/fieldpilot30_v1_int8.onnx
```

Then confirm the whole stack still agrees with itself:

```bash
python scripts/check_hardware.py --demo
python scripts/verify_system.py          # needs the API running
pytest tests/ -q
```

Every one of those paths falls back to the stock model if the file is missing,
so a half-finished copy degrades honestly instead of crashing — but it also
means a typo'd path silently keeps the OLD model. Check the startup log line
that names which weights actually loaded.
