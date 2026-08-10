from __future__ import annotations

import pytest

from measurecv.core.exceptions import MeasureCVError


class TestSynthesize:
    def test_raises_measurecv_error_when_piper_binary_is_missing(self, monkeypatch) -> None:
        from measurecv.voice.tts import synthesize

        monkeypatch.setenv("PATH", "")  # no `piper` reachable anywhere
        with pytest.raises(MeasureCVError, match="piper"):
            synthesize("hello")

    def test_real_synthesis_produces_a_wav_file(self) -> None:
        pytest.importorskip("piper")
        from measurecv.voice.tts import synthesize, voice_model_path

        if not voice_model_path().is_file():
            pytest.skip("voice model not downloaded; see tts.py docstring")

        audio = synthesize("testing one two three")
        assert audio[:4] == b"RIFF"
        assert len(audio) > 1000
