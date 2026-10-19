"""WER-харнесс и парсинг строк InfoBayAI."""

import wave
from pathlib import Path

from polylog.datasets.infobayai import (
    extract_audio,
    extract_transcript,
    sidecar_from_row,
)
from polylog.datasets.wer import normalize_ru, wer, wer_detail


def test_normalize_ru():
    assert normalize_ru("Привет, Ёлка-Ёж!") == ["привет", "елка", "еж"]
    assert normalize_ru("") == []


def test_wer_identical_is_zero():
    assert wer("добрый день как дела", "Добрый день, как дела?") == 0.0


def test_wer_known_value():
    # ref=3 слова, гипотеза потеряла одно → 1/3
    assert abs(wer("привет как дела", "привет дела") - 1 / 3) < 1e-9


def test_wer_empty_reference():
    assert wer("", "что-то") == 1.0
    assert wer("", "") == 0.0


def test_wer_detail_decomposition():
    d = wer_detail("а б в г", "а x в")
    assert d["sub"] == 1  # б→x
    assert d["del"] == 1  # г потерян
    assert d["ins"] == 0
    assert abs(d["wer"] - 0.5) < 1e-9


def test_extract_audio_infobayai_list_shape():
    """Реальный shape InfoBayAI: audio = [{src: URL, type: audio/wav}]."""
    row = {
        "audio": [
            {"src": "https://huggingface.co/datasets/InfoBayAI/X/resolve/main/a.wav", "type": "audio/wav"}
        ]
    }
    url, path, blob = extract_audio(row)
    assert url and "resolve" in url
    assert path == "a.wav"
    assert blob is None


def test_extract_audio_standard_shape():
    row = {"audio": {"bytes": b"xx", "path": "f.wav", "url": None}}
    url, path, blob = extract_audio(row)
    assert blob == b"xx" and path == "f.wav"


def test_extract_transcript_candidates():
    row = {"transcript": "  Здравствуйте! ", "other": 1}
    text, col = extract_transcript(row)
    assert text == "Здравствуйте!" and col == "transcript"
    row2 = {"meta": "x", "description": "Разговор о поставке оборудования на склад"}
    text2, col2 = extract_transcript(row2)
    assert col2 == "description"


def test_sidecar_from_row():
    assert sidecar_from_row(None) == []
    sc = sidecar_from_row("Привет", duration_ms=5000)
    assert sc[0]["speaker"] == "unknown"
    assert sc[0]["end_ms"] == 5000


def test_dev_resampler_8k_to_16k(tmp_path: Path):
    """Dev-ресемплер: длина удваивается, формат PCM16/16к (реальная телефония 8к)."""
    import io

    from polylog.media.normalize import normalize_call_audio

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * 8000)  # 1 c на 8 кГц
    src = tmp_path / "tel8k.wav"
    src.write_bytes(buf.getvalue())

    norm = normalize_call_audio(src, tmp_path / "out.wav")
    assert norm.dev_resampled is True or norm.sample_rate == 16_000
    assert abs(norm.duration_sec - 1.0) < 0.05
    with wave.open(str(tmp_path / "out.wav"), "rb") as w:
        assert w.getframerate() == 16_000
        assert w.getnframes() == 16_000


def test_dev_resampler_stereo_8k_to_16k(tmp_path: Path):
    """Регресс: стерео (интерливинг каналов) не падает с IndexError."""
    import io

    from polylog.media.normalize import normalize_call_audio

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * 2 * 8000)  # 1 c стерео на 8 кГц
    src = tmp_path / "tel8k_stereo.wav"
    src.write_bytes(buf.getvalue())

    norm = normalize_call_audio(src, tmp_path / "out.wav")
    assert norm.channels == 2
    assert norm.channels_map == {"0": "agent", "1": "client"}
    assert abs(norm.duration_sec - 1.0) < 0.05
    with wave.open(str(tmp_path / "out.wav"), "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == 16_000
        assert w.getnframes() == 16_000
