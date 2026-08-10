"""
Gemma 4 backend — the parts that must hold with no weights on disk.

The 8B model cannot be loaded in CI, on a 6 GB laptop GPU, or on any machine
that has not pulled ~5 GB of weights. So what is tested here is everything that
decides what happens when it *isn't* loaded: that importing the module is free,
that failures are reported rather than faked, and that a caller can always tell
"no objects found" from "the brain never ran". Those are the properties that
keep a missing model from silently becoming a confident empty answer.
"""

import asyncio
import base64
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.vision.gemma_analyzer import (  # noqa: E402
    GemmaAnalyzer,
    _extract_json,
    _scene_error,
    _unavailable,
)


def _jpeg_b64(size=(64, 64)) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 120, 120)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


class TestJsonExtraction:
    """Instruction-tuned models fence and preamble their JSON; the parser must cope."""

    def test_bare_object(self):
        assert _extract_json('{"objects": []}') == {"objects": []}

    def test_fenced(self):
        raw = '```json\n{"objects": [{"label": "rebar cage"}]}\n```'
        assert _extract_json(raw) == {"objects": [{"label": "rebar cage"}]}

    def test_fenced_without_language_tag(self):
        assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_preamble_and_trailer(self):
        assert _extract_json('Sure!\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_nested_braces_survive(self):
        raw = '{"objects": [{"label": "pipe", "box_2d": [1, 2, 3, 4]}]}'
        assert _extract_json(raw)["objects"][0]["box_2d"] == [1, 2, 3, 4]

    @pytest.mark.parametrize("bad", ["", "no json here", "[1,2,3]", "{unclosed"])
    def test_unparseable_returns_none_not_empty_dict(self, bad):
        # None and {} must stay distinguishable: {} would read as a successful
        # parse of an empty result, which is the exact confusion this avoids.
        assert _extract_json(bad) is None


class TestFailureContract:
    def test_unavailable_shape(self):
        r = _unavailable("weights missing")
        assert r["status"] == "unavailable"
        assert r["reason"] == "weights missing"
        assert r["objects"] == []

    def test_scene_error_matches_vlmanalyzer_keys(self):
        """Both backends must fail with the same keys or callers need a branch."""
        from agents.vision.vlm_analyzer import VLMAnalyzer

        gemma_keys = set(_scene_error("boom"))
        gemini_keys = set(VLMAnalyzer.__dict__["_error_result"](None, "boom"))
        assert gemini_keys <= gemma_keys

    def test_scene_error_carries_no_fabricated_content(self):
        r = _scene_error("cuda oom")
        assert r["confidence"] == 0.0
        assert r["safety_hazards"] == [] and r["compliance_issues"] == []
        assert "cuda oom" in r["scene_description"]
        assert r["engineer_alert_needed"] is False


class TestDegradation:
    """No weights present -> every path reports why, none of them invent output."""

    def test_import_is_free_and_unloaded_by_default(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        assert a.available is False
        assert a.status()["loaded"] is False

    def test_status_does_not_trigger_a_load(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        a.status()
        assert a._loaded is False        # an 8B load must never be a side effect

    def test_identify_objects_reports_reason(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        r = asyncio.run(a.identify_objects(_jpeg_b64()))
        assert r["status"] == "unavailable"
        assert r["objects"] == []
        assert r["reason"]

    def test_analyze_scene_reports_reason(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        r = asyncio.run(a.analyze_scene(_jpeg_b64(), "A12"))
        assert r["confidence"] == 0.0
        assert "Error analyzing scene" in r["scene_description"]

    def test_load_failure_is_cached_not_retried_per_request(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        asyncio.run(a.identify_objects(_jpeg_b64()))
        first = a.load_error
        asyncio.run(a.identify_objects(_jpeg_b64()))
        assert a.load_error == first and first is not None

    def test_singleton_is_shared(self):
        assert GemmaAnalyzer.instance() is GemmaAnalyzer.instance()


class TestBackendSelection:
    def test_default_backend_is_gemini(self, monkeypatch):
        """An unconfigured checkout must behave exactly as it did pre-Gemma."""
        monkeypatch.delenv("VLM_BACKEND", raising=False)
        import importlib

        import agents.vision.vlm_analyzer as mod
        importlib.reload(mod)
        assert mod.VLM_BACKEND == "gemini"
        assert mod.VLMAnalyzer()._gemma is None

    def test_gemma_backend_selects_local(self):
        from agents.vision.vlm_analyzer import VLMAnalyzer
        assert VLMAnalyzer(backend="gemma")._gemma is not None

    def test_identify_objects_refuses_on_gemini_backend(self):
        """Must not be quietly served from the API — that would fake an offline claim."""
        from agents.vision.vlm_analyzer import VLMAnalyzer
        r = asyncio.run(VLMAnalyzer(backend="gemini").identify_objects(_jpeg_b64()))
        assert r["status"] == "unavailable"
        assert "gemma" in r["reason"].lower()


class TestLlamaCppRuntime:
    """The GGUF path: a 6 GB-GPU-shaped runtime that talks HTTP to llama-server."""

    def test_refused_connection_names_the_fix(self):
        """Server down is a distinct, actionable failure — not a generic error."""
        a = GemmaAnalyzer(runtime="llama_cpp")
        r = asyncio.run(a.identify_objects(_jpeg_b64()))
        assert r["status"] == "unavailable"
        assert "serve_gemma_gguf" in r["reason"]

    def test_server_with_no_model_is_distinct_from_server_down(self, monkeypatch):
        import requests

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return {"data": []}

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
        a = GemmaAnalyzer(runtime="llama_cpp")
        assert a._load() is False
        assert "no model loaded" in a.load_error

    @staticmethod
    def _stub_models(monkeypatch, ids):
        import requests

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return {"data": [{"id": i} for i in ids]}

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

    def test_single_model_server_adopts_what_it_holds(self, monkeypatch):
        """llama-server ignores the requested id; status must not lie about it."""
        self._stub_models(monkeypatch, ["gemma-4-E4B-it-Q4_0.gguf"])
        a = GemmaAnalyzer(model_id="whatever-we-asked-for", runtime="llama_cpp")
        assert a._load() is True
        assert a.status()["model_id"] == "gemma-4-E4B-it-Q4_0.gguf"
        assert a.status()["runtime"] == "llama_cpp"

    def test_multi_model_server_honours_the_configured_id(self, monkeypatch):
        """Ollama dispatches on the model field — picking [0] could route to a
        text-only model sitting next to the vision one."""
        self._stub_models(monkeypatch, ["huihui-gemma4-coder:latest", "gemma4:e4b-it-qat"])
        a = GemmaAnalyzer(model_id="gemma4:e4b-it-qat", runtime="llama_cpp")
        assert a._load() is True
        assert a.status()["model_id"] == "gemma4:e4b-it-qat"

    def test_multi_model_server_refuses_when_configured_id_absent(self, monkeypatch):
        """Silently falling through to another model is how an image reaches a
        text-only one and fails as an opaque 400 three layers later."""
        self._stub_models(monkeypatch, ["huihui-gemma4-coder:latest", "llama3:8b"])
        a = GemmaAnalyzer(model_id="gemma4:e4b-it-qat", runtime="llama_cpp")
        assert a._load() is False
        assert "not served" in a.load_error
        assert "huihui-gemma4-coder:latest" in a.load_error   # lists what IS there

    def test_quantization_field_reflects_gguf_not_bitsandbytes(self):
        assert GemmaAnalyzer(runtime="llama_cpp").quantization == "gguf"
        assert GemmaAnalyzer(runtime="transformers").quantization != "gguf"

    def test_sends_image_and_returns_parsed_objects(self, monkeypatch):
        """End-to-end through the HTTP path with the server stubbed."""
        import requests

        sent = {}

        class _Get:
            def raise_for_status(self): pass
            def json(self): return {"data": [{"id": "gguf"}]}

        class _Post:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {
                    "content": '{"objects": [{"label": "rebar cage", "confidence": 0.8}]}'
                }}]}

        def _post(url, json=None, timeout=None):
            sent.update(url=url, payload=json)
            return _Post()

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Get())
        monkeypatch.setattr(requests, "post", _post)

        a = GemmaAnalyzer(runtime="llama_cpp")
        r = asyncio.run(a.identify_objects(_jpeg_b64()))

        assert r["status"] == "ok"
        assert r["objects"][0]["label"] == "rebar cage"
        assert "chat/completions" in sent["url"]
        parts = sent["payload"]["messages"][0]["content"]
        assert any(p["type"] == "image_url" for p in parts), "image must actually be sent"
        assert sent["payload"]["temperature"] == 0.0, "identification must be deterministic"

    def test_boxes_are_flagged_unverified(self, monkeypatch):
        """Model-reported coordinates must never be mistaken for metrology output."""
        import requests

        class _Get:
            def raise_for_status(self): pass
            def json(self): return {"data": [{"id": "gguf"}]}

        class _Post:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {
                    "content": '{"objects": [{"label": "pipe", "box_2d": [1,2,3,4]}]}'
                }}]}

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Get())
        monkeypatch.setattr(requests, "post", lambda *a, **k: _Post())

        r = asyncio.run(GemmaAnalyzer(runtime="llama_cpp").identify_objects(_jpeg_b64()))
        assert r["boxes_verified"] is False

    def test_text_only_model_rejection_names_the_real_cause(self, monkeypatch):
        """A text-only model 400s on an image; the body holds the whole diagnosis.

        Verified against a live Ollama serving huihui-gemma4-coder — it answers
        with a double-encoded OpenAI error whose inner message is
        "model does not support multimodal requests". Losing that to a bare
        "HTTP 400" would send someone debugging their wiring instead of their
        model choice.
        """
        import requests

        class _Get:
            def raise_for_status(self): pass
            def json(self): return {"data": [{"id": "coder"}]}

        class _Post:
            status_code = 400
            text = "..."
            def json(self):
                return {"error": {"message": json.dumps({"error": {
                    "code": 400,
                    "message": "Multimodal data provided, but model does not "
                               "support multimodal requests.",
                    "type": "invalid_request_error"}}),
                    "type": "invalid_request_error"}}

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Get())
        monkeypatch.setattr(requests, "post", lambda *a, **k: _Post())

        r = asyncio.run(GemmaAnalyzer(runtime="llama_cpp").identify_objects(_jpeg_b64()))
        assert r["status"] == "unavailable"
        assert "does not support multimodal" in r["reason"]

    @pytest.mark.parametrize("body,want", [
        ({"error": {"message": "plain"}}, "plain"),
        ({"error": {"message": '{"error": {"message": "nested"}}'}}, "nested"),
        ({"error": "bare string"}, "bare string"),
        ({"unexpected": 1}, "unexpected"),          # degrades, never raises
    ])
    def test_server_error_unwrapping(self, body, want):
        from agents.vision.gemma_analyzer import _server_error

        class _R:
            def json(self): return body
        assert want in _server_error(_R())

    def test_server_error_survives_non_json(self):
        from agents.vision.gemma_analyzer import _server_error

        class _R:
            text = "502 Bad Gateway"
            def json(self): raise ValueError("not json")
        assert "502" in _server_error(_R())

    def test_unparseable_response_is_a_fault_not_an_empty_result(self, monkeypatch):
        import requests

        class _Get:
            def raise_for_status(self): pass
            def json(self): return {"data": [{"id": "gguf"}]}

        class _Post:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": "I see a construction site."}}]}

        monkeypatch.setattr(requests, "get", lambda *a, **k: _Get())
        monkeypatch.setattr(requests, "post", lambda *a, **k: _Post())

        r = asyncio.run(GemmaAnalyzer(runtime="llama_cpp").identify_objects(_jpeg_b64()))
        assert r["status"] == "unavailable"        # NOT ok-with-zero-objects
        assert r["objects"] == []


class TestImageDecoding:
    def test_rejects_garbage_without_raising(self):
        a = GemmaAnalyzer(model_id="does-not-exist/nope")
        r = asyncio.run(a.identify_objects("!!!not base64!!!"))
        assert r["status"] == "unavailable"

    def test_accepts_data_url_prefix(self):
        """The worker page posts canvas frames with the data: prefix attached."""
        a = GemmaAnalyzer()
        img = a._decode_image("data:image/jpeg;base64," + _jpeg_b64())
        assert img.size == (64, 64) and img.mode == "RGB"
