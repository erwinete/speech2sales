"""Чистые функции GigaAM-адаптера: чанкинг и сборка реплик (без загрузки модели)."""

from polylog.asr.base import Word
from polylog.asr.gigaam import chunk_bounds, words_to_utterances


def test_chunk_bounds_25s():
    assert chunk_bounds(62.0) == [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0), (60.0, 62.0)]


def test_chunk_bounds_short_and_zero():
    assert chunk_bounds(10.0) == [(0.0, 10.0)]
    assert chunk_bounds(0.0) == []
    assert chunk_bounds(20.0) == [(0.0, 20.0)]


def test_words_to_utterances_gap_split():
    words = [
        Word("привет", 0, 500),
        Word("день", 600, 1000),
        Word("как", 5000, 5300),   # пауза 4 c → новая реплика
        Word("дела", 5400, 5800),
    ]
    utts = words_to_utterances(words, gap_ms=600, speaker="agent")
    assert len(utts) == 2
    assert utts[0].text == "привет день"
    assert utts[0].start_ms == 0 and utts[0].end_ms == 1000
    assert utts[1].text == "как дела"
    assert utts[1].speaker == "agent"


def test_words_to_utterances_empty():
    assert words_to_utterances([]) == []


def test_turn_chunks_long_mono():
    """Длинный транз диаризации (монолог полевой записи) режется <=20 c."""
    from polylog.asr.gigaam import turn_chunks

    chunks = turn_chunks(30_000, 85_000)  # 55 c речи
    spans = [(a, b) for a, b in chunks]
    assert len(spans) == 3
    assert spans[0] == (30_000, 50_000)
    assert spans[1] == (50_000, 70_000)
    assert spans[2] == (70_000, 85_000)
    # все куски <= 20 c и стыкуются без дыр
    for a, b in spans:
        assert b - a <= 20_000
    for i in range(len(spans) - 1):
        assert spans[i + 1][0] == spans[i][1]  # стыкуются без дыр


def test_turn_chunks_short_and_degenerate():
    from polylog.asr.gigaam import turn_chunks

    assert turn_chunks(1_000, 2_500) == [(1_000, 2_500)]
    assert turn_chunks(5_000, 5_000) == []
