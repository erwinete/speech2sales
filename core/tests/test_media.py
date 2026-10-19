"""Нормализация аудио: fast path 16к PCM без ffmpeg, детерминизм."""

import shutil
import wave
from pathlib import Path

import pytest
from conftest import wav_bytes

from polylog.media.normalize import MediaError, normalize_call_audio


def test_fast_path_reuses_16k_wav(tmp_path: Path):
    src = tmp_path / "call.wav"
    src.write_bytes(wav_bytes(seconds=4.0))
    norm = normalize_call_audio(src, tmp_path / "out.wav")
    assert norm.reused is True
    assert norm.channels == 1
    assert norm.sample_rate == 16_000
    assert 3.9 <= norm.duration_sec <= 4.1
    assert norm.channels_map is None
    assert not (tmp_path / "out.wav").exists()  # копия не создавалась


def test_stereo_gets_channel_map(tmp_path: Path):
    src = tmp_path / "stereo.wav"
    src.write_bytes(wav_bytes(seconds=2.0, channels=2))
    norm = normalize_call_audio(src)
    assert norm.channels == 2
    assert norm.channels_map == {"0": "agent", "1": "client"}


def test_mono_8000hz_needs_conversion_or_raises(tmp_path: Path):
    src = tmp_path / "tel.wav"
    src.write_bytes(wav_bytes(seconds=2.0, rate=8000))
    has_ffmpeg = shutil.which("ffmpeg") is not None
    if has_ffmpeg:
        norm = normalize_call_audio(src, tmp_path / "conv.wav")
        assert norm.reused is False
        assert norm.sample_rate == 16_000
        assert (tmp_path / "conv.wav").is_file()
    else:
        # без ffmpeg работает dev-ресемплер (линейная интерполяция)
        norm = normalize_call_audio(src, tmp_path / "conv.wav")
        assert norm.dev_resampled is True
        assert norm.sample_rate == 16_000
        assert abs(norm.duration_sec - 2.0) < 0.05


def test_missing_source_raises(tmp_path: Path):
    with pytest.raises(MediaError, match="не найден"):
        normalize_call_audio(tmp_path / "nope.wav", tmp_path / "out.wav")


def test_garbage_raises_without_ffmpeg(tmp_path: Path):
    garbage = tmp_path / "g.bin"
    garbage.write_bytes(b"\x00" * 100)
    if shutil.which("ffmpeg") is not None:
        pytest.skip("ffmpeg установлен — гистерезис не проверить на этой машине")
    with pytest.raises(MediaError):
        normalize_call_audio(garbage, tmp_path / "out.wav")


def test_probe_wav_readable():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "a.wav"
        p.write_bytes(wav_bytes(1.0))
        with wave.open(str(p), "rb") as w:
            assert w.getframerate() == 16_000
