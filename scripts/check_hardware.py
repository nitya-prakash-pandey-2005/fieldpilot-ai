#!/usr/bin/env python
"""
Will this machine run FieldPilot — and which parts of it?

Two machines run this project and they have opposite problems. The demo laptop
has a small GPU and needs every model to FIT. The lab container has a big GPU
that is SHARED, so what matters there is the free slice, not the card.
`scripts/verify_system.py` answers "are the services up"; this answers the
question that comes before it: "does the hardware allow this at all".

    python scripts/check_hardware.py            # what can this machine do
    python scripts/check_hardware.py --demo     # only the demo path
    python scripts/check_hardware.py --train    # only the training path

Exit code 0 if the selected profile is runnable, 1 if something required is out
of reach. Nothing here downloads or loads a model — it reads capacities and
compares them against the real measured footprints recorded below.

WHY THE NUMBERS ARE WHAT THEY ARE. Every figure in FOOTPRINTS was measured on
this project, not estimated from parameter counts:

  - gemma4:e4b-it-qat reports 3.1 GB resident at 100% GPU (`ollama ps`), even
    though the download is 6.15 GB. Quantised weights do not occupy their file
    size once loaded.
  - gemma4:12b reports 8.1 GB and lands 42%/58% CPU/GPU on a 6 GB card, where a
    single reasoning call exceeded a 600 s timeout. That is the line between
    "slow" and "unusable", and it is why 12b is not the demo model.
  - The YOLO/depth figures come from the stack the demo actually loads.
  - Training figures follow docs/TRAINING_PLAN.md §3's known-good points
    (batch 16 @ 960 ~ 24 GB, batch 8 @ 960 ~ 16 GB).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

# name -> (vram_gb_when_loaded, required, note)
# `required` means the demo cannot proceed without it.
DEMO_FOOTPRINTS = [
    ("YOLO11n + PPE + pose (Agent 1/4)", 1.2, True,
     "torch CPU works too, just slower — this is the GPU-resident figure"),
    ("Metric3D depth (Agent 2)",         1.4, False,
     "optional: without it, ArUco still gives the most accurate scale (±1–2 mm)"),
    ("gemma4:e4b-it-qat (VLM brain)",    3.1, False,
     "optional: VLM_BACKEND=gemini needs no VRAM at all"),
    ("Kokoro-82M TTS (edge speech)",     0.4, False,
     "optional: cloud TTS needs no VRAM"),
]

# (label, imgsz, batch) -> estimated GB, mirroring train_detector.vram_preflight
TRAIN_CONFIGS = [
    ("yolo11m-seg  batch 16 @ 960  (script default)", 960, 16),
    ("yolo11m-seg  batch  8 @ 960",                   960,  8),
    ("yolo11m-seg  batch  4 @ 960",                   960,  4),
    ("yolo11m-seg  batch  8 @ 800",                   800,  8),
    ("yolo11m-seg  batch  4 @ 800",                   800,  4),
]


def _train_estimate(imgsz: int, batch: int) -> float:
    """Same coarse fit as models/training/train_detector.py — keep them in step."""
    return 1.5 + batch * (imgsz / 960.0) ** 2 * 1.4


def gpu_info() -> tuple[float, float, str] | None:
    """(free_gb, total_gb, name) from the live driver, or None if no CUDA."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        free_b, total_b = torch.cuda.mem_get_info()
        return free_b / 1e9, total_b / 1e9, torch.cuda.get_device_name(0)
    except Exception:
        pass
    # torch missing is not the same as no GPU — the lab container may not have
    # installed it yet. Fall back to the driver directly.
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0 and out.stdout.strip():
            f, t, name = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            return float(f) / 1024, float(t) / 1024, name
    except Exception:
        pass
    return None


def host_ram_gb() -> float | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1e6
    except Exception:
        return None
    return None


def check_demo(free: float | None) -> bool:
    print("\n── DEMO PATH " + "─" * 52)
    total_req = sum(g for _, g, req, _ in DEMO_FOOTPRINTS if req)
    total_all = sum(g for _, g, _, _ in DEMO_FOOTPRINTS)

    for name, gb, required, note in DEMO_FOOTPRINTS:
        if free is None:
            verdict = "CPU"
        elif gb <= free:
            verdict = "fits"
        else:
            verdict = "TOO BIG"
        tag = "required" if required else "optional"
        print(f"  {verdict:>8}  {gb:4.1f} GB  {name}  [{tag}]")
        if note:
            print(f"            {note}")

    print(f"\n  required total: {total_req:.1f} GB   everything: {total_all:.1f} GB")

    if free is None:
        print("  → No GPU detected. The demo still runs on CPU: YOLO is slower,\n"
              "    and set VLM_BACKEND=gemini so no local VLM is needed.")
        return True
    if total_all <= free:
        print(f"  → All of it fits in {free:.1f} GB free. Run the full local stack.")
        return True
    if total_req <= free:
        print(f"  → Required models fit in {free:.1f} GB. Not everything does:")
        budget = free - total_req
        for name, gb, required, _ in DEMO_FOOTPRINTS:
            if not required and gb > budget:
                print(f"      drop or offload: {name} ({gb:.1f} GB)")
        print("    Cheapest fix is VLM_BACKEND=gemini — the VLM is the biggest\n"
              "    optional block and the cloud path costs no VRAM.")
        return True
    print(f"  → Required models ({total_req:.1f} GB) exceed {free:.1f} GB free.\n"
          "    Free VRAM (`ollama stop <model>`) or run Agent 1 on CPU.")
    return False


def check_train(free: float | None, total: float | None) -> bool:
    print("\n── TRAINING PATH (T1 detector) " + "─" * 34)
    if free is None:
        print("  No GPU. Training here is not realistic — docs/TRAINING_PLAN.md §1.\n"
              "  Use the lab container; this repo is set up to be cloned there.")
        return False

    if total and (total - free) > 2.0:
        print(f"  ⚠ SHARED GPU: {total - free:.1f} of {total:.1f} GB is already in use.\n"
              f"    Plan against the {free:.1f} GB free, not the card size — and expect\n"
              f"    it to shrink if a neighbour allocates. Use --resume.\n")

    ok_any = False
    for label, imgsz, batch in TRAIN_CONFIGS:
        est = _train_estimate(imgsz, batch)
        fits = est <= free * 0.92          # headroom for fragmentation
        ok_any |= fits
        print(f"  {'fits' if fits else 'OOM ':>8}  ~{est:4.1f} GB  {label}")

    if ok_any:
        best = next((l, i, b) for l, i, b in TRAIN_CONFIGS
                    if _train_estimate(i, b) <= free * 0.92)
        print(f"\n  → Largest config that fits: {best[0].strip()}")
        print(f"    python models/training/train_detector.py \\\n"
              f"        --data data/training/fieldpilot30/fieldpilot30.yaml \\\n"
              f"        --model yolo11m-seg.pt --imgsz {best[1]} --batch {best[2]} \\\n"
              f"        --epochs 120 --name fieldpilot30_v1")
        print("    imgsz is the biggest accuracy lever for rebar/conduit — drop batch\n"
              "    before dropping imgsz (docs/TRAINING_PLAN.md §3).")
    else:
        print(f"\n  → Nothing fits {free:.1f} GB free. Use yolo11s-seg instead of\n"
              "    yolo11m-seg, or wait for the shared card to free up.")
    return ok_any


def check_tools() -> None:
    print("\n── TOOLING " + "─" * 54)
    for mod, why in [("torch", "required"), ("ultralytics", "Agent 1 + training"),
                     ("cv2", "measurement"), ("langgraph", "orchestrator"),
                     ("transformers", "depth + Gemma transformers path"),
                     ("roboflow", "dataset download (training only)")]:
        try:
            __import__(mod)
            print(f"  ok       {mod}  ({why})")
        except ImportError:
            print(f"  MISSING  {mod}  ({why})")
    print(f"  {'ok      ' if shutil.which('ollama') else 'absent  '} "
          f"ollama  (local VLM; optional)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="only the demo profile")
    ap.add_argument("--train", action="store_true", help="only the training profile")
    args = ap.parse_args()
    both = not (args.demo or args.train)

    gpu = gpu_info()
    ram = host_ram_gb()

    print("═" * 66)
    if gpu:
        free, total, name = gpu
        print(f"  GPU  {name}")
        print(f"       {free:.1f} GB free of {total:.1f} GB")
    else:
        free = total = None
        print("  GPU  none detected (CPU-only)")
    print(f"  RAM  {ram:.1f} GB available" if ram else "  RAM  unknown")
    print("═" * 66)

    ok = True
    if both or args.demo:
        ok &= check_demo(free)
    if both or args.train:
        ok &= check_train(free, total)
    check_tools()
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
