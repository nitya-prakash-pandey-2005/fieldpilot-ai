# syntax=docker/dockerfile:1.7
#
# Multi-stage build for measurecv.
#
# Stage layout is driven by layer caching: dependencies change rarely and are
# ~6 GB, application code changes constantly and is ~1 MB. Installing them in
# separate layers means a code edit rebuilds in seconds rather than re-pulling
# the CUDA wheels.
#
#   docker build -f docker/Dockerfile -t measurecv:gpu .
#   docker build -f docker/Dockerfile --target cpu -t measurecv:cpu .

# ---------------------------------------------------------------------------
# Base: shared OS layer
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Keep model downloads on a mounted volume, not in the image layer.
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3-pip \
        # OpenCV runtime deps. libgl1/libglib2.0 are required even by the
        # headless build for its image codecs.
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        # Needed for video decode; without it VideoCapture silently fails on H.264.
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python && python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ---------------------------------------------------------------------------
# Builder: install dependencies
# ---------------------------------------------------------------------------
FROM base AS builder

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/measurecv/__init__.py src/measurecv/__init__.py

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel \
    && pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
    && pip install ".[models,api]"

# ---------------------------------------------------------------------------
# Runtime (GPU)
# ---------------------------------------------------------------------------
FROM base AS runtime

COPY --from=builder /opt/venv /opt/venv

# Never run as root. A container that pulls arbitrary model weights and opens
# operator-supplied RTSP URLs should have as little authority as possible.
RUN groupadd --gid 1000 measurecv \
    && useradd --uid 1000 --gid 1000 --create-home measurecv \
    && mkdir -p /models /app/outputs \
    && chown -R measurecv:measurecv /models /app

WORKDIR /app
COPY --chown=measurecv:measurecv src/ ./src/
COPY --chown=measurecv:measurecv configs/ ./configs/
COPY --chown=measurecv:measurecv pyproject.toml README.md ./

RUN pip install --no-deps -e . && chown -R measurecv:measurecv /app

USER measurecv

ENV MEASURECV_CONFIG=/app/configs/default.yaml \
    MEASURECV__LOG_JSON=true \
    MEASURECV__API__HOST=0.0.0.0 \
    MEASURECV__API__PORT=8000

EXPOSE 8000

# /health stays 200 while the process lives; /ready reports model readiness.
# Liveness must not fail during a multi-gigabyte checkpoint load, or the
# orchestrator will kill the container partway through loading -- forever.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["measurecv"]
CMD ["serve"]

# ---------------------------------------------------------------------------
# CPU-only variant: much smaller, for CI and edge boxes without a GPU
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY configs/ ./configs/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install ".[models,api]"

RUN useradd --uid 1000 --create-home measurecv \
    && mkdir -p /models /app/outputs \
    && chown -R measurecv:measurecv /models /app
USER measurecv

ENV MEASURECV_CONFIG=/app/configs/default.yaml \
    MEASURECV__LOG_JSON=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["measurecv"]
CMD ["serve"]
