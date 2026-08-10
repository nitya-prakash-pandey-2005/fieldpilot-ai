"""
Gemma 4 — the open-vocabulary brain behind Agent 1.

WHY THIS EXISTS. YOLO11n can only name what it was trained on: 80 COCO classes,
plus the PPE and forklift heads bolted on beside it. A construction site is full
of things none of those models has a label for — rebar cages, formwork panels,
scaffold couplers, cable tray, conduit runs, shuttering, waterproofing membrane.
The detector sees them as pixels and reports nothing, and Agent 2 cannot measure
an asset that Agent 1 never named. docs/TRAINING_PLAN.md's answer is to fine-tune
a 28-class taxonomy (job T1, 10-16 GPU hours, still a closed vocabulary).

This module is the other answer: ask a multimodal model what it is looking at, in
open vocabulary, with no class list at all. Gemma 4 is Apache-2.0, which also
makes it the only reasoning path in this repo that does not carry either the
Ultralytics AGPL obligation or a per-call dependency on someone's API being up.

WHAT IT DOES NOT REPLACE. YOLO stays. It is ~7 s/frame slower here than a
detector has any right to be, but it produces calibrated boxes that Agent 2's
metrology consumes and that this model does not reliably produce. The division is
deliberate:

    YOLO      -> where things are      (boxes, tracked, metric-grade)
    Gemma 4   -> what things are       (open-vocabulary labels, scene reasoning)

`identify_objects()` is the "what". `analyze_scene()` matches VLMAnalyzer's dict
contract exactly so the two are interchangeable at the call site.

HARDWARE, HONESTLY. `gemma-4-E4B-it` is 8B parameters. In bf16 that is ~16 GB of
weights and it will not load on a 6 GB laptop GPU. Defaults here are 4-bit NF4
(~5 GB) with `device_map="auto"`, which lets accelerate spill whatever does not
fit to CPU rather than dying with an OOM. On a 6 GB card sharing space with YOLO
that spill is not hypothetical, and CPU-resident layers cost seconds per frame.
This is a reasoning path for a captured frame, not for a live video loop — the
duty-cycled "analyse this frame" call, not the 30 fps one.

Nothing here invents a result. If transformers is too old, the weights are not
downloaded, or CUDA runs out of memory, `available` goes False, `load_error` says
which one it was, and every method returns `status: "unavailable"` carrying that
reason. A brain that guesses when it cannot see is worse than no brain.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
import re
import threading
import time
from typing import Any, Optional

# `AutoModelForMultimodalLM` is the Gemma 4 loading path and it does not exist
# before transformers 5.0 — on 4.x the import raises ImportError, which is why
# every transformers symbol here is imported lazily inside _load() rather than at
# module scope. Importing this module must stay free on a 4.x install, because
# api/main.py imports the whole route tree at startup and one hard ImportError
# here would take the entire API down rather than degrading one agent.
MODEL_ID = os.getenv("GEMMA_MODEL_ID", "google/gemma-4-E4B-it")

# transformers | llama_cpp
#
# WHY TWO RUNTIMES. `google/gemma-4-E4B-it` is published as a SINGLE 16 GB
# safetensors shard. Even at 4-bit that is a 16 GB download, and bitsandbytes
# has to stream the bf16 shard to quantize it — on a 6 GB GPU with ~5 GB of
# free host RAM the result is swap thrashing, not inference. The transformers
# path below is correct and is the right one on a >=16 GB card; it is simply not
# runnable on a laptop.
#
# `llama_cpp` points at a llama.cpp server holding the same model as GGUF:
# Q4_0 is 4.59 GB plus a 0.56 GB vision projector, mmap'd, which does fit. It
# is served over HTTP rather than bound in-process for three reasons: the
# OpenAI-compatible shape is already how this repo talks to self-hosted models
# (LLM_BACKEND=vllm in utils/llm_client.py), it adds no compiled Python
# dependency, and it keeps 5 GB of weights in a separate process from the API —
# which matters when YOLO is competing for the same 6 GB of VRAM.
RUNTIME = os.getenv("GEMMA_RUNTIME", "transformers").lower()

# Only read when RUNTIME=llama_cpp. Points at llama-server's OpenAI-compatible
# endpoint; scripts/serve_gemma_gguf.py launches one with the right flags.
LLAMA_CPP_URL = os.getenv("GEMMA_LLAMA_CPP_URL", "http://127.0.0.1:8080/v1")
LLAMA_CPP_TIMEOUT = float(os.getenv("GEMMA_LLAMA_CPP_TIMEOUT", "180"))

# 4bit | 8bit | none. Default 4-bit: see HARDWARE above. "none" is bf16 and needs
# ~16 GB — correct on a workstation card, fatal on this laptop.
# Ignored when RUNTIME=llama_cpp: the GGUF file's own quantization decides.
QUANTIZATION = os.getenv("GEMMA_QUANTIZATION", "4bit").lower()

# 1536, not 512. Gemma 4 is a reasoning model: Ollama reports a `thinking`
# capability and returns the chain in a separate `reasoning` field, but those
# tokens come out of the SAME budget. At 512 the model spent the whole allowance
# thinking and returned an empty `content` — verified against gemma4:12b, which
# reasoned correctly about rebar and chairs and then had nothing left to answer
# with. The failure looked like a parser bug and was a budget bug.
MAX_NEW_TOKENS = int(os.getenv("GEMMA_MAX_NEW_TOKENS", "1536"))
DEVICE_MAP = os.getenv("GEMMA_DEVICE_MAP", "auto")

# Loading 8B of weights takes minutes on a cold cache. Doing it inside a request
# would hold the event loop; doing it twice concurrently would try to place two
# copies on a 6 GB card. One lock, one load, everyone else waits.
_LOAD_LOCK = threading.Lock()

_MIN_TRANSFORMERS_MAJOR = 5


def _unavailable(reason: str) -> dict:
    """The single shape every failure returns. `status` is what callers branch on."""
    return {
        "status": "unavailable",
        "reason": reason,
        "objects": [],
        "backend": "gemma4",
    }


class GemmaAnalyzer:
    """Local Gemma 4 multimodal inference. Lazy, single-instance, fail-loud-but-soft."""

    _instance: Optional["GemmaAnalyzer"] = None

    def __init__(self, model_id: str = MODEL_ID, runtime: str = None) -> None:
        self.model_id = model_id
        self.runtime = (runtime or RUNTIME).lower()
        self.model = None
        self.processor = None
        self.load_error: Optional[str] = None
        self._loaded = False
        self.device: Optional[str] = None
        self.quantization = QUANTIZATION if self.runtime == "transformers" else "gguf"

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def instance(cls) -> "GemmaAnalyzer":
        """Process-wide singleton. 8B of weights is not a per-request object."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def available(self) -> bool:
        return self._loaded and self.model is not None

    def _load(self) -> bool:
        """Load once. Returns availability; records why not in `load_error`.

        Never raises. Callers treat a False return as "this agent is degraded",
        which is the same contract agents/edge/runtime.py uses for a missing ONNX
        export, and the API stays up either way.
        """
        if self._loaded or self.load_error:
            return self.available

        with _LOAD_LOCK:
            if self._loaded or self.load_error:      # another thread got there first
                return self.available

            if self.runtime == "llama_cpp":
                return self._probe_llama_cpp()

            try:
                import transformers
            except ImportError as e:
                self.load_error = f"transformers not installed ({e})"
                return False

            major = int(transformers.__version__.split(".")[0])
            if major < _MIN_TRANSFORMERS_MAJOR:
                # The precise, actionable version of "it didn't work". Gemma 4's
                # loader class simply is not in the 4.x namespace.
                self.load_error = (
                    f"transformers {transformers.__version__} has no "
                    f"AutoModelForMultimodalLM — Gemma 4 needs >={_MIN_TRANSFORMERS_MAJOR}.0. "
                    f"Run: pip install -U 'transformers>=5.0'"
                )
                return False

            try:
                from transformers import AutoModelForMultimodalLM, AutoProcessor
            except ImportError as e:
                self.load_error = f"AutoModelForMultimodalLM unavailable: {e}"
                return False

            kwargs: dict[str, Any] = {"device_map": DEVICE_MAP, "dtype": "auto"}

            if self.quantization in ("4bit", "8bit"):
                try:
                    import torch
                    from transformers import BitsAndBytesConfig
                except ImportError as e:
                    self.load_error = (
                        f"{self.quantization} quantization needs bitsandbytes: {e} — "
                        f"run pip install bitsandbytes, or set GEMMA_QUANTIZATION=none"
                    )
                    return False

                if self.quantization == "4bit":
                    kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_quant_type="nf4",
                        # Double quantization saves a further ~0.4 GB, which is not
                        # rounding error when the budget is 6 GB total.
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_compute_dtype=torch.bfloat16,
                    )
                else:
                    kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)

            t0 = time.time()
            try:
                self.processor = AutoProcessor.from_pretrained(self.model_id)
                self.model = AutoModelForMultimodalLM.from_pretrained(self.model_id, **kwargs)
            except Exception as e:                  # OOM, 401 on a gated repo, no net
                self.load_error = f"{type(e).__name__}: {e}"
                self.model = None
                self.processor = None
                return False

            self.device = str(getattr(self.model, "device", "unknown"))
            self._loaded = True
            print(
                f"[GEMMA] {self.model_id} loaded in {time.time() - t0:.1f}s "
                f"({self.quantization}, device={self.device})"
            )
            return True

    def _probe_llama_cpp(self) -> bool:
        """Check the llama.cpp server is up and holding a model.

        Cheap (one GET) and honest: a refused connection means the server is not
        running, which is a different fix from a server running with no mmproj,
        so the two are reported differently rather than as one "unavailable".
        """
        import requests

        try:
            r = requests.get(f"{LLAMA_CPP_URL}/models", timeout=10)
            r.raise_for_status()
            served = [m.get("id") for m in (r.json().get("data") or [])]
        except requests.exceptions.ConnectionError:
            self.load_error = (
                f"no llama.cpp server at {LLAMA_CPP_URL} — start one with "
                f"python scripts/serve_gemma_gguf.py"
            )
            return False
        except Exception as e:
            self.load_error = f"llama.cpp server probe failed — {type(e).__name__}: {e}"
            return False

        if not served:
            self.load_error = f"llama.cpp server at {LLAMA_CPP_URL} has no model loaded"
            return False

        # Two server behaviours to satisfy at once. llama-server ignores the
        # `model` field and serves the single GGUF it was launched with, so
        # whatever it reports IS the model. Ollama serves MANY models and
        # dispatches on that field — and a host running this project plausibly
        # has a text-only Gemma sitting alongside the vision one. Blindly taking
        # served[0] there would silently route an image at a model that cannot
        # see it, which fails as an opaque HTTP 400 several layers later.
        # So: honour the configured id when the server actually has it.
        if self.model_id in served:
            pass                                   # asked-for model is available
        elif len(served) == 1:
            self.model_id = served[0]              # single-model server: it's that one
        else:
            self.load_error = (
                f"{self.model_id!r} not served by {LLAMA_CPP_URL}. Available: "
                f"{', '.join(map(str, served[:8]))}. Set GEMMA_MODEL_ID to one of them "
                f"— and make sure it is vision-capable (`ollama show <name>` must "
                f"list a `vision` capability)."
            )
            return False
        self.device = f"llama.cpp @ {LLAMA_CPP_URL}"
        self.model = object()          # sentinel: `available` is about readiness
        self._loaded = True
        print(f"[GEMMA] llama.cpp serving {self.model_id} at {LLAMA_CPP_URL}")
        return True

    def _generate_llama_cpp(self, image, prompt: str) -> str:
        """One multimodal turn against llama-server's OpenAI-compatible endpoint."""
        import requests

        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=90)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

        r = requests.post(
            f"{LLAMA_CPP_URL}/chat/completions",
            json={
                "model": self.model_id,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                "max_tokens": MAX_NEW_TOKENS,
                # Greedy, matching the transformers path — same reasoning: an
                # identification that feeds an inspection record must be stable.
                "temperature": 0.0,
            },
            timeout=LLAMA_CPP_TIMEOUT,
        )

        if r.status_code >= 400:
            # The status line alone is close to useless here. A text-only model
            # served by Ollama answers an image request with a bare 400 whose
            # BODY says "model does not support multimodal requests" — which is
            # the whole diagnosis. Surfacing it turns "HTTP 400" into a message
            # that names the actual problem: wrong model, not wrong wiring.
            raise RuntimeError(f"HTTP {r.status_code} from {LLAMA_CPP_URL}: "
                               f"{_server_error(r)}")

        choice = r.json()["choices"][0]
        content = choice["message"].get("content") or ""

        if not content.strip():
            # Distinguish "spent the budget thinking" from "said nothing". The
            # first is a config fix, the second is a model problem, and reporting
            # both as unparseable JSON sends you to the wrong one.
            reasoning = (choice["message"].get("reasoning") or "").strip()
            finish = choice.get("finish_reason")
            if reasoning or finish == "length":
                raise RuntimeError(
                    f"model returned reasoning but no answer (finish_reason={finish}). "
                    f"Raise GEMMA_MAX_NEW_TOKENS above {MAX_NEW_TOKENS} — thinking "
                    f"tokens share this budget."
                )
            raise RuntimeError(f"model returned empty content (finish_reason={finish})")

        return content

    def status(self) -> dict:
        """Report state without forcing a multi-minute load. For /health."""
        return {
            "model_id": self.model_id,
            "runtime": self.runtime,
            "loaded": self._loaded,
            "available": self.available,
            "quantization": self.quantization,
            "device": self.device,
            "load_error": self.load_error,
        }

    # -- inference ---------------------------------------------------------

    def _generate(self, image, prompt: str) -> str:
        """One multimodal turn. Blocking — callers must use asyncio.to_thread."""
        if self.runtime == "llama_cpp":
            return self._generate_llama_cpp(image, prompt)

        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }]

        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            add_generation_prompt=True,
        ).to(self.model.device)

        prompt_len = inputs["input_ids"].shape[-1]

        import torch
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                # Identification is an extraction task, not a creative one. Greedy
                # decoding keeps the same frame giving the same answer, which
                # matters when the answer becomes an inspection record.
                do_sample=False,
            )

        # Slice off the prompt — decoding the whole sequence would echo the
        # instructions back and the JSON parser would find the schema example
        # before the actual answer.
        return self.processor.decode(outputs[0][prompt_len:], skip_special_tokens=True)

    def _decode_image(self, image_b64: str):
        from PIL import Image
        # Tolerate a data: URL — the worker page posts frames straight from a
        # canvas and those arrive with the prefix attached.
        if "," in image_b64[:64] and image_b64.lstrip().startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        raw = base64.b64decode(image_b64, validate=True)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    # -- the object-identification brain -----------------------------------

    async def identify_objects(self, image_b64: str, hint: str = "") -> dict:
        """Name what is in the frame, open vocabulary.

        This is the capability YOLO does not have: no class list is supplied, so
        "rebar cage", "formwork panel" and "cable tray" are as available to it as
        "person". Returns labels with the model's own confidence, and boxes only
        when it volunteers them.
        """
        if not await asyncio.to_thread(self._load):
            return _unavailable(self.load_error or "not loaded")

        try:
            image = self._decode_image(image_b64)
        except (binascii.Error, ValueError, OSError) as e:
            return _unavailable(f"undecodable image: {e}")

        # Kept deliberately short. Gemma 4 is a reasoning model and prompt
        # complexity translates directly into thinking tokens — the long,
        # fully-specified version of this prompt (confidence + count + box_2d +
        # rules for each) made gemma4:12b reason past a 1536-token budget and
        # return nothing at all. Asking for less gets an answer; asking for a
        # richer schema got an empty string. Optional fields are parsed if the
        # model volunteers them, but are not demanded here.
        prompt = (
            "Construction site inspection. List every distinct object and material you see. "
            "Use construction terms (rebar, formwork, scaffold, conduit, cable tray, "
            "hard hat, safety vest, excavator).\n"
            + (f"Focus on: {hint}\n" if hint else "")
            + 'JSON only: {"objects": [{"label": "...", "confidence": 0.0}]}'
        )

        t0 = time.time()
        try:
            raw = await asyncio.to_thread(self._generate, image, prompt)
        except Exception as e:
            # OOM at generate time is a distinct failure from OOM at load time and
            # is worth reporting as itself.
            return _unavailable(f"inference failed — {type(e).__name__}: {e}")

        parsed = _extract_json(raw)
        if parsed is None:
            return _unavailable(f"model did not return parseable JSON: {raw[:200]!r}")

        objects = parsed.get("objects") or []
        if not isinstance(objects, list):
            return _unavailable(f"'objects' was {type(objects).__name__}, expected list")

        return {
            "status": "ok",
            "backend": f"gemma4:{self.model_id}",
            "objects": [o for o in objects if isinstance(o, dict) and o.get("label")],
            "latency_ms": round((time.time() - t0) * 1000),
            "device": self.device,
            # Gemma 4's card lists object detection and pointing as capabilities but
            # documents no coordinate contract, and nothing here has been validated
            # against ground truth. Labels are the trustworthy output; boxes are the
            # model's unverified claim and must not feed metrology.
            "boxes_verified": False,
        }

    # -- VLMAnalyzer-compatible scene analysis ------------------------------

    async def analyze_scene(
        self,
        image_base64: str,
        zone_id: str,
        language: str = "en",
        worker_query: Optional[str] = None,
        project_context: str = "",
    ) -> dict:
        """Drop-in local replacement for VLMAnalyzer.analyze_scene.

        Same keys out, so api/routes/vision.py and worker.py need no branch. On
        failure it returns the same error shape VLMAnalyzer uses, with the reason
        in `scene_description` rather than a plausible-sounding fake scene.
        """
        if not await asyncio.to_thread(self._load):
            return _scene_error(self.load_error or "not loaded")

        try:
            image = self._decode_image(image_base64)
        except (binascii.Error, ValueError, OSError) as e:
            return _scene_error(f"undecodable image: {e}")

        query = worker_query or (
            "What is happening in this construction scene? "
            "Any safety issues or compliance concerns?"
        )
        prompt = (
            f"You are an AI construction site assistant seeing through a worker's smart glasses.\n"
            f"Zone: {zone_id}\n"
            f"Language to respond in: {language}\n"
            f"Project context: {project_context}\n\n"
            f"Worker question: {query}\n\n"
            "Respond with JSON only, exactly these keys:\n"
            '{"scene_description": "what you see", "work_type": "type of work", '
            '"safety_hazards": [], "compliance_issues": [], '
            '"urgency": "low|medium|high|critical", '
            f'"spoken_response": "response in {language}", '
            '"engineer_alert_needed": false, "confidence": 0.9}'
        )

        try:
            raw = await asyncio.to_thread(self._generate, image, prompt)
        except Exception as e:
            return _scene_error(f"inference failed — {type(e).__name__}: {e}")

        parsed = _extract_json(raw)
        if parsed is None:
            return _scene_error(f"model did not return parseable JSON: {raw[:200]!r}")

        parsed.setdefault("safety_hazards", [])
        parsed.setdefault("compliance_issues", [])
        parsed.setdefault("urgency", "low")
        parsed.setdefault("engineer_alert_needed", False)
        parsed.setdefault("confidence", 0.0)
        parsed["backend"] = f"gemma4:{self.model_id}"
        return parsed


def _server_error(resp) -> str:
    """Dig the human-readable message out of an OpenAI-style error body.

    Ollama double-encodes it — the JSON `error.message` is itself a JSON string
    holding the real message — so one unwrap is not always enough.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]

    msg = body
    for _ in range(6):                      # bounded: never loop on hostile input
        if isinstance(msg, dict):
            nxt = msg.get("message", msg.get("error"))
            if nxt is None or nxt is msg:
                break
            msg = nxt
            continue
        if isinstance(msg, str) and msg.lstrip().startswith("{"):
            try:
                msg = json.loads(msg)
                continue
            except json.JSONDecodeError:
                break
        break
    return str(msg)[:300]


def _scene_error(error: str) -> dict:
    """VLMAnalyzer._error_result's shape, so both backends fail identically."""
    return {
        "scene_description": f"Error analyzing scene: {error}",
        "work_type": "Unknown",
        "safety_hazards": [],
        "compliance_issues": [],
        "urgency": "low",
        "spoken_response": "I encountered an error analyzing this scene.",
        "engineer_alert_needed": False,
        "confidence": 0.0,
        "backend": "gemma4",
    }


def _extract_json(text: str) -> Optional[dict]:
    """Pull one JSON object out of a model response.

    Instruction-tuned models wrap JSON in ```json fences or a sentence of
    preamble often enough that a bare json.loads is the wrong default. Returns
    None rather than {} on failure — the caller must be able to tell "the model
    said nothing usable" from "the model found nothing", because the first is a
    fault and the second is a valid empty result.
    """
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    # Self-check: the parser and the failure contract, neither of which needs
    # 8B of weights. Run: python -m agents.vision.gemma_analyzer
    assert _extract_json('{"objects": []}') == {"objects": []}
    assert _extract_json('```json\n{"objects": [{"label": "rebar"}]}\n```') == {
        "objects": [{"label": "rebar"}]
    }
    assert _extract_json('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}
    assert _extract_json("no json here") is None
    assert _extract_json("") is None
    assert _extract_json("[1, 2, 3]") is None          # array is not the contract

    err = _unavailable("weights missing")
    assert err["status"] == "unavailable" and err["objects"] == []
    scene = _scene_error("boom")
    assert scene["confidence"] == 0.0 and scene["safety_hazards"] == []

    a = GemmaAnalyzer(model_id="does-not-exist/nope")
    assert a.available is False
    st = a.status()
    assert st["loaded"] is False and st["model_id"] == "does-not-exist/nope"

    print("gemma_analyzer self-check OK")
    print(json.dumps(GemmaAnalyzer.instance().status(), indent=2))
