"""Авто-flip стерео (DoD М3 §1) и voiceprint агентов (DoD М3 §2.1).

Чистые функции решателей — без моделей; персист карты каналов пайплайном —
через фейковый бэкенд; enrollment отпечатков — на sqlite-сессии."""

import uuid

from conftest import AUTH, wav_bytes

from polylog.asr.diarize import (
    assign_roles,
    channel_role_score,
    cosine,
    decide_channel_roles,
    voice_agent_speaker,
)


def test_decide_channel_roles_flip():
    """Маркеры агента на ch1, карта коннектора говорит ch0=agent → переворот."""
    head_texts = {"0": "да, слушаю", "1": "добрый день, компания опт-торг, меня зовут иван"}
    new_map, status = decide_channel_roles(head_texts, {"0": "agent", "1": "client"})
    assert status == "auto_flipped"
    assert new_map["0"] == "client" and new_map["1"] == "agent"
    assert new_map["_status"] == "auto_flipped"


def test_decide_channel_roles_confirmed():
    head_texts = {"0": "алло, здравствуйте, компания", "1": "да, хорошо"}
    new_map, status = decide_channel_roles(head_texts, {"0": "agent", "1": "client"})
    assert status == "confirmed"
    assert new_map["0"] == "agent" and new_map["_status"] == "confirmed"


def test_decide_channel_roles_from_connector_when_no_markers():
    """Ни маркеров, ни речи («да»/«алло») → доверяем карте коннектора."""
    head_texts = {"0": "да, да", "1": "алло"}
    new_map, status = decide_channel_roles(head_texts, {"0": "agent", "1": "client"})
    assert status == "from_connector"
    assert new_map == {"0": "agent", "1": "client"}
    assert "_status" not in new_map


def test_decide_channel_roles_by_markers_without_agent_in_map():
    """Карта без agent (unknown) → роли назначаются маркерами."""
    head_texts = {"0": "алло", "1": "здравствуйте, слушаю вас"}
    new_map, status = decide_channel_roles(head_texts, {"0": "unknown", "1": "unknown"})
    assert status == "by_markers"
    assert new_map["1"] == "agent" and new_map["0"] == "client"


def test_decide_channel_roles_no_map():
    new_map, status = decide_channel_roles({"0": "здравствуйте"}, None)
    assert status == "no_map" and new_map is None


def test_channel_role_score_and_cosine():
    assert channel_role_score("добрый день, компания х, меня зовут пётр") >= 2
    assert channel_role_score("да, хорошо, спасибо") == 0
    a, b = [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]
    c = [0.0, 1.0, 0.0]
    assert cosine(a, b) == 1.0
    assert cosine(a, c) == 0.0
    assert cosine(a, [1.0, 0.0]) == 0.0  # разная длина
    assert cosine([], []) == 0.0


def test_voice_agent_speaker():
    agent_voice = [1.0, 0.2, 0.0]
    client_voice = [0.0, 0.1, 1.0]
    vectors = {"SPEAKER_00": agent_voice, "SPEAKER_01": client_voice}
    assert voice_agent_speaker(vectors, {"101": agent_voice}) == "SPEAKER_00"
    # ниже порога — None (не агент)
    weak = [0.0, 0.2, 1.0]
    assert voice_agent_speaker({"SPEAKER_00": weak}, {"101": agent_voice}, threshold=0.9) is None
    # без отпечатков — None
    assert voice_agent_speaker(vectors, None) is None


def test_assign_roles_voice_overrides_markers():
    """Голосовой отпечаток приоритетнее маркеров: агент нарушил скрипт,
    но опознан по голосу; у клиента — продающие фразы (цитирует компанию)."""
    texts = {"S0": "мы компания лидер, предлагаем бесплатно", "S1": "алло, слушаю вас"}
    # маркеры выбрали бы S0; голос говорит S1
    role_map = assign_roles(
        [
            {"speaker": "S0", "start_ms": 0, "end_ms": 1000},
            {"speaker": "S1", "start_ms": 1500, "end_ms": 3000},
        ],
        texts,
        speaker_vectors={"S0": [0.0, 1.0, 0.0], "S1": [1.0, 0.0, 0.0]},
        agent_voices={"101": [1.0, 0.0, 0.0]},
    )
    assert role_map["S1"] == "agent" and role_map["S0"] == "client"
    # без голосов — как раньше, по маркерам (turns пересоздаём: assign_roles
    # переписывает поле speaker на месте)
    role_map2 = assign_roles(
        [
            {"speaker": "S0", "start_ms": 0, "end_ms": 1000},
            {"speaker": "S1", "start_ms": 1500, "end_ms": 3000},
        ],
        texts,
    )
    assert role_map2["S0"] == "agent"


async def test_enroll_agent_voice_averages(app_client):
    """Повторный enrollment усредняет вектор и увеличивает samples."""
    from sqlalchemy import select

    from polylog.asr.voiceprint import enroll_agent_voice, get_agent_voices
    from polylog.models.graph import AgentVoice

    client, app = app_client
    await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("a.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_from": "101", "phone_to": "+79001112222"},
    )
    async with app.state.sessionmaker() as s:
        org_id = uuid.UUID(
            (await s.execute(__import__("sqlalchemy").text("SELECT id FROM orgs LIMIT 1"))).scalar()
        )
        await enroll_agent_voice(s, org_id, "101", [1.0, 0.0], "test")
        await enroll_agent_voice(s, org_id, "101", [0.0, 1.0], "test")
        await s.commit()

        rows = (await s.execute(select(AgentVoice))).scalars().all()
        assert len(rows) == 1
        assert rows[0].samples == 2
        assert rows[0].vector == [0.5, 0.5]

        voices = await get_agent_voices(s, org_id)
        assert voices == {"101": [0.5, 0.5]}


async def test_pipeline_persists_flipped_map(app_client, monkeypatch):
    """stage_transcribe вызывает prepare_channels и сохраняет обновлённую
    карту каналов (со статусом) в звонке. Стерео-WAV → normalize ставит
    дефолтную карту {"0": agent, "1": client} → фейковый бэкенд её переворачивает."""
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(3.0, channels=2), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79004440000"},
    )
    call_id = uuid.UUID(r.json()["call"]["id"])

    class FlipBackend:
        id = "flip-fake"

        def prepare_channels(self, wav_path, channels_map):
            return {**channels_map, "0": "client", "1": "agent", "_status": "auto_flipped"}, "auto_flipped"

        def transcribe(self, wav_path, channels_map=None, hints=None):
            from polylog.asr.base import Utterance

            return [Utterance(speaker=channels_map.get("0", "unknown"), start_ms=0, end_ms=500, text="тест")]

    import polylog.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "get_backend", lambda name: FlipBackend())

    # reprocess на done — no-op: ломаем состояние как после ошибки стадии
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as s:
        from polylog.models.calls import Call

        call = await s.get(Call, call_id)
        call.state = "failed"
        await s.commit()

    r2 = await client.post(f"/api/v1/calls/{call_id}/reprocess", headers=AUTH)
    assert r2.status_code == 200, r2.text

    async with sessionmaker() as s:
        from polylog.models.calls import Call

        call = await s.get(Call, call_id)
        assert call.channels_map is not None
        assert call.channels_map["1"] == "agent"
        assert call.channels_map["0"] == "client"
        assert call.channels_map["_status"] == "auto_flipped"
