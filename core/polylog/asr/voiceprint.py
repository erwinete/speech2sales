"""Voiceprint DB (DoD М3 §2.1): голосовые отпечатки агентов.

Стерео-звонок с разрешённой картой каналов — чистый источник голоса агента:
канал агента вырезается и прогоняется через pyannote embedding (whole-window).
На mono отпечатки подсказывают роль спикера там, где текстовой эвристики
недостаточно (агент нарушил скрипт, клиент цитирует компанию, маркеров нет).

Включение: env POLYLOG_VOICEPRINT=1 (+ HF_TOKEN, как у диаризации).
Ключ агента — внутренний номер АТС (прокси до «сотрудников» из CRM, M2).
Отпечатки в таблице agent_voices (JSON-вектор, инкрементальное среднее) —
агентов ≤200, косинус считается в Python без pgvector.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("polylog.asr.voiceprint")

# Speaker-эмбеддинг-модель (ResNet34, 256-dim) — уже в HF-кэше машины
EMBED_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
_inference = None


def available() -> bool:
    from polylog.asr.diarize import _token

    return os.environ.get("POLYLOG_VOICEPRINT", "") == "1" and _token() is not None


def _get_inference():
    global _inference
    if _inference is None:
        # torchaudio до pyannote: на Windows его импорт подключает совместимые
        # ffmpeg-DLL (иначе torchcodec в Inference.crop не находит avcodec)
        try:
            import torchaudio  # noqa: F401
        except ImportError:  # pragma: no cover — Linux-контур
            pass
        from pyannote.audio import Inference, Model

        from polylog.asr.diarize import _token

        model = Model.from_pretrained(EMBED_MODEL, use_auth_token=_token())
        _inference = Inference(model, window="whole")
    return _inference


def _to_vector(res) -> list[float]:
    import numpy as np

    arr = np.asarray(res, dtype=float)
    if arr.ndim > 1:
        arr = arr.mean(axis=0)
    return [float(x) for x in arr]


def channel_embedding(wav_path: Path, channel: int) -> list[float]:
    """Эмбеддинг целого канала стерео — голос одного спикера (enrollment)."""
    from polylog.asr.gigaam import GigaAMBackend

    with tempfile.TemporaryDirectory(prefix="polylog-voice-") as td:
        mono = Path(td) / "ch.wav"
        GigaAMBackend._extract_channel(wav_path, channel, mono)
        res = _get_inference()(str(mono))
    return _to_vector(res)


def speaker_embeddings(wav_path: Path, turns: list[dict]) -> dict[str, list[float]]:
    """Усреднённый эмбеддинг каждого сырого спикера по его транзам (mono)."""
    import numpy as np
    from pyannote.core import Segment

    inference = _get_inference()
    acc: dict[str, list[list[float]]] = {}
    for t in turns:
        try:
            res = inference.crop(
                str(wav_path), Segment(t["start_ms"] / 1000, t["end_ms"] / 1000)
            )
        except Exception as e:  # noqa: BLE001 — короткий/тихий сегмент не фатален
            log.debug("crop %s-%s мс не удался: %s", t["start_ms"], t["end_ms"], e)
            continue
        arr = np.asarray(res, dtype=float)
        if arr.ndim > 1:
            arr = arr.mean(axis=0)
        acc.setdefault(t["speaker"], []).append([float(x) for x in arr])
    return {spk: [float(x) for x in np.asarray(vs).mean(axis=0)] for spk, vs in acc.items()}


async def enroll_agent_voice(
    session: AsyncSession, org_id, agent_key: str, vector: list[float], model_id: str
) -> None:
    """Инкрементальное усреднение отпечатка (upsert). Смена размерности модели —
    отсчёт заново."""
    from polylog.models.graph import AgentVoice

    row = (
        await session.execute(
            select(AgentVoice).where(
                AgentVoice.org_id == org_id, AgentVoice.agent_key == agent_key
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            AgentVoice(
                org_id=org_id, agent_key=agent_key, vector=vector, samples=1, model_id=model_id
            )
        )
        return
    old = row.vector or []
    if len(old) != len(vector):
        row.vector, row.samples, row.model_id = vector, 1, model_id
        return
    n = row.samples or 1
    row.vector = [(o * n + v) / (n + 1) for o, v in zip(old, vector, strict=True)]
    row.samples = n + 1


async def get_agent_voices(session: AsyncSession, org_id) -> dict[str, list[float]]:
    """Все отпечатки организации: {agent_key: vector}."""
    from polylog.models.graph import AgentVoice

    rows = (
        (
            await session.execute(
                select(AgentVoice).where(AgentVoice.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )
    return {r.agent_key: r.vector for r in rows}
