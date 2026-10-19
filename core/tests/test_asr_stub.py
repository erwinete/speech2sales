"""Stub-ASR: sidecar-транскрипты и fallback-сегментация."""

import json
from pathlib import Path

from conftest import wav_bytes

from polylog.asr.base import AsrBackendError, get_backend
from polylog.asr.stub import StubAsrBackend


def test_sidecar_transcript(tmp_path: Path):
    wav = tmp_path / "call.wav"
    wav.write_bytes(wav_bytes(4.0))
    (tmp_path / "call.transcript.json").write_text(
        json.dumps([
            {"speaker": "agent", "start_ms": 0, "end_ms": 2000, "text": "Добрый день!"},
            {"speaker": "client", "start_ms": 2300, "end_ms": 4000, "text": "Здравствуйте.", "conf": 0.9},
        ]),
        encoding="utf-8",
    )
    out = StubAsrBackend().transcribe(wav, {"0": "agent", "1": "client"})
    assert [u.speaker for u in out] == ["agent", "client"]
    assert out[0].text == "Добрый день!"
    assert out[1].conf == 0.9


def test_fallback_segments_alternate_roles(tmp_path: Path):
    wav = tmp_path / "c.wav"
    wav.write_bytes(wav_bytes(11.0))
    out = StubAsrBackend().transcribe(wav, None)
    assert len(out) == 3
    assert out[0].start_ms == 0
    assert out[-1].end_ms == 11_000
    assert {u.speaker for u in out} == {"agent", "client"}


def test_missing_file_raises():
    try:
        StubAsrBackend().transcribe(Path("nope.wav"), None)
        raise AssertionError("ожидался AsrBackendError")
    except AsrBackendError:
        pass


def test_registry_unknown_backend():
    try:
        get_backend("no-such")
        raise AssertionError("ожидался AsrBackendError")
    except AsrBackendError as e:
        assert "stub" in str(e)
