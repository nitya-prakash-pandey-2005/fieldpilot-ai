#!/usr/bin/env python
"""
Serve Gemma 4 as GGUF so the 8B brain fits on a 6 GB laptop GPU.

WHY THIS EXISTS. `google/gemma-4-E4B-it` on the Hub is a single 16 GB
safetensors shard. transformers + bitsandbytes has to stream that whole shard to
quantize it, so "4-bit" still means a 16 GB download and a host-RAM spike this
machine does not have. The GGUF build is already quantized on disk:

    gemma-4-E4B-it-Q4_0.gguf        4.59 GB   the model
    mmproj-...-Q8_0.gguf            0.56 GB   the vision projector

llama.cpp mmaps them, so pages it is not using stay on disk instead of in RAM,
and `--n-gpu-layers` decides how much rides on the GPU. That is the difference
between "does not load" and "runs".

WHY A SEPARATE PROCESS. Two reasons, both practical. YOLO already wants most of
a 6 GB card, and a crashed model process should not take the FastAPI app with
it. llama-server speaks the OpenAI chat-completions shape, which is what
agents/vision/gemma_analyzer.py's llama_cpp runtime talks to and what
utils/llm_client.py already uses for self-hosted models.

    python scripts/serve_gemma_gguf.py            # download if needed, serve
    python scripts/serve_gemma_gguf.py --check    # report readiness, serve nothing
    python scripts/serve_gemma_gguf.py --quant Q8_0 --n-gpu-layers 20

Then, in the API's environment:

    VLM_BACKEND=gemma
    GEMMA_RUNTIME=llama_cpp

WHAT THIS DOES NOT DO. It does not build llama.cpp. If `llama-server` is not on
PATH it says so and points at the install, because compiling llama.cpp with CUDA
from inside a helper script is a worse failure mode than being told to run one
command.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request

REPO = "ggml-org/gemma-4-E4B-it-GGUF"

# Q4_0 is the default because it is the only one that leaves headroom on a 6 GB
# card once YOLO has taken its share. Sizes are the real published ones.
QUANTS = {
    "Q4_0": ("gemma-4-E4B-it-Q4_0.gguf", 4.59),
    "Q8_0": ("gemma-4-E4B-it-Q8_0.gguf", 8.03),
    "BF16": ("gemma-4-E4B-it-BF16.gguf", 15.05),
}

# The vision half. Without it llama-server loads and answers text questions
# while silently ignoring every image — which for an object-identification brain
# is the worst possible failure, because it looks like it is working.
MMPROJ = {
    "Q8_0": ("mmproj-gemma-4-E4B-it-Q8_0.gguf", 0.56),
    "BF16": ("mmproj-gemma-4-E4B-it-BF16.gguf", 0.99),
}

WEIGHTS_DIR = os.getenv("GEMMA_GGUF_DIR", "models/weights/gemma4")


def _url(filename: str) -> str:
    return f"https://huggingface.co/{REPO}/resolve/main/{filename}?download=true"


def _download(filename: str, size_gb: float, dest_dir: str) -> str:
    dest = os.path.join(dest_dir, filename)
    if os.path.exists(dest):
        have = os.path.getsize(dest) / 1e9
        # A partial download left by an interrupted run is worse than none: it
        # exists, so it looks complete, and llama-server fails deep inside the
        # loader with a confusing error. 5% tolerance covers GB-vs-GiB reporting.
        if have >= size_gb * 0.95:
            print(f"  have  {filename}  ({have:.2f} GB)")
            return dest
        print(f"  partial {filename} ({have:.2f} of {size_gb:.2f} GB) — refetching")
        os.remove(dest)

    print(f"  fetch {filename}  ({size_gb:.2f} GB)")
    tmp = dest + ".part"

    def _progress(blocks, block_size, total):
        if total <= 0:
            return
        pct = min(100, blocks * block_size * 100 // total)
        if pct % 5 == 0:
            print(f"\r        {pct:3d}%", end="", flush=True)

    urllib.request.urlretrieve(_url(filename), tmp, reporthook=_progress)
    print()
    os.replace(tmp, dest)          # atomic: a killed run never leaves a whole-looking file
    return dest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quant", default="Q4_0", choices=list(QUANTS))
    p.add_argument("--mmproj", default="Q8_0", choices=list(MMPROJ))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--n-gpu-layers", type=int, default=99,
                   help="layers on GPU; lower it if you OOM against YOLO (default: all)")
    p.add_argument("--ctx-size", type=int, default=4096)
    p.add_argument("--check", action="store_true",
                   help="report what is present and exit without serving")
    args = p.parse_args()

    server = shutil.which("llama-server")
    model_file, model_gb = QUANTS[args.quant]
    mmproj_file, mmproj_gb = MMPROJ[args.mmproj]
    model_path = os.path.join(WEIGHTS_DIR, model_file)
    mmproj_path = os.path.join(WEIGHTS_DIR, mmproj_file)

    if args.check:
        print(f"llama-server : {server or 'NOT ON PATH'}")
        for label, path, gb in (("model ", model_path, model_gb),
                                ("mmproj", mmproj_path, mmproj_gb)):
            if os.path.exists(path):
                print(f"{label}       : {os.path.getsize(path) / 1e9:.2f} / {gb:.2f} GB  {path}")
            else:
                print(f"{label}       : missing  {path}")
        print(f"total needed : {model_gb + mmproj_gb:.2f} GB")
        return 0

    if not server:
        print(
            "llama-server is not on PATH.\n\n"
            "  Arch/Manjaro : sudo pacman -S llama.cpp\n"
            "  Prebuilt     : https://github.com/ggml-org/llama.cpp/releases\n"
            "  From source  : cmake -B build -DGGML_CUDA=ON && cmake --build build -j\n\n"
            "Then re-run this script.",
            file=sys.stderr,
        )
        return 1

    os.makedirs(WEIGHTS_DIR, exist_ok=True)
    print(f"Weights in {WEIGHTS_DIR} ({model_gb + mmproj_gb:.2f} GB total):")
    try:
        _download(model_file, model_gb, WEIGHTS_DIR)
        _download(mmproj_file, mmproj_gb, WEIGHTS_DIR)
    except (urllib.error.URLError, OSError) as e:
        print(f"\ndownload failed: {e}", file=sys.stderr)
        return 1

    cmd = [
        server,
        "--model", model_path,
        "--mmproj", mmproj_path,        # drop this and images are silently ignored
        "--host", args.host,
        "--port", str(args.port),
        "--n-gpu-layers", str(args.n_gpu_layers),
        "--ctx-size", str(args.ctx_size),
    ]
    print("\n" + " ".join(cmd) + "\n")
    print(f"Point the API at it:  VLM_BACKEND=gemma GEMMA_RUNTIME=llama_cpp")
    print(f"Endpoint:             http://{args.host}:{args.port}/v1\n")

    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
