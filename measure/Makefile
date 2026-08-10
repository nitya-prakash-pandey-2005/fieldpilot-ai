.DEFAULT_GOAL := help
.PHONY: help install install-dev install-all test test-fast test-accuracy lint format \
        typecheck check coverage clean docker docker-cpu serve demo bench calibrate-example

PYTHON ?= python
PKG    := src/measurecv

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install:  ## Install the core library (no torch)
	$(PYTHON) -m pip install -e .

install-dev:  ## Install with test tooling (no model weights needed)
	$(PYTHON) -m pip install -e ".[api,dev]"

install-all:  ## Install everything, including torch and the model backends
	$(PYTHON) -m pip install -e ".[all]"

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
test:  ## Run the full test-suite
	$(PYTHON) -m pytest -q

test-fast:  ## Skip slow and weight-dependent tests
	$(PYTHON) -m pytest -q -m "not slow and not weights and not gpu"

test-accuracy:  ## Only the tests that assert against analytic ground truth
	$(PYTHON) -m pytest tests/test_geometry.py tests/test_measurement.py \
	                    tests/test_calibration.py tests/test_models.py -q

coverage:  ## Test with an HTML coverage report
	$(PYTHON) -m pytest --cov=measurecv --cov-report=html --cov-report=term-missing
	@echo "report: htmlcov/index.html"

lint:  ## Check style
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:  ## Auto-format and fix what can be fixed
	$(PYTHON) -m ruff check src tests --fix
	$(PYTHON) -m ruff format src tests

typecheck:  ## Static type analysis
	$(PYTHON) -m mypy $(PKG)

check: lint typecheck test  ## Everything CI runs

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
serve:  ## Start the API on :8000
	measurecv serve

demo:  ## Exercise the whole pipeline with no weights and no GPU
	measurecv benchmark --dry-run -n 5 --warmup 2

bench:  ## Benchmark per-stage latency with the real models
	measurecv benchmark -n 20 --warmup 3

calibrate-example:  ## Calibrate from ./calibration_images
	measurecv calibrate ./calibration_images --board 9x6 --square-size 0.025 \
		-o calibration/camera.json

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
docker:  ## Build the GPU image
	docker build -f docker/Dockerfile --target runtime -t measurecv:gpu .

docker-cpu:  ## Build the CPU-only image
	docker build -f docker/Dockerfile --target cpu -t measurecv:cpu .

up:  ## Start the stack
	docker compose -f docker/docker-compose.yml up -d

up-monitoring:  ## Start the stack with Prometheus and Grafana
	docker compose -f docker/docker-compose.yml --profile monitoring up -d

down:  ## Stop the stack
	docker compose -f docker/docker-compose.yml down

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
clean:  ## Remove build and test artefacts
	rm -rf build dist *.egg-info src/*.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
