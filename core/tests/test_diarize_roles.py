"""Выбор агента по маркерам речи (mono-роли, doc 02 §2.3)."""

from polylog.asr.diarize import pick_agent_speaker


def test_agent_by_pitch_markers():
    texts = {
        "SPEAKER_00": "Ну, в основном разницу",
        "SPEAKER_01": "Я звоню к вам с предложением по оптовым продажам. Меня зовут Ирина",
    }
    assert pick_agent_speaker(texts) == "SPEAKER_01"


def test_agent_fallback_to_first_speaker():
    texts = {"S1": "алё", "S2": "да, слушаю"}
    assert pick_agent_speaker(texts, first_speaker="S1") == "S1"


def test_agent_no_texts():
    assert pick_agent_speaker({}, first_speaker="S1") is None
