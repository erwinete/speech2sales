import logging
import os
import re
from pathlib import Path

log = logging.getLogger("polylog.asr.diarize")

_pipeline = None


def _token() -> str | None:
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def available() -> bool:
    """Флаг настройки: pyannote включён и токен есть (модель проверится при загрузке)."""
    return os.environ.get("POLYLOG_DIARIZATION", "") == "pyannote" and _token() is not None


def _ensure_pipeline():
    global _pipeline
    if _pipeline is None:
        import torch
        from pyannote.audio import Pipeline

        token = _token()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("pyannote: загрузка speaker-diarization-3.1 (device=%s)…", device)
        _pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token
        ).to(torch.device(device))
    return _pipeline


def diarize(wav_path: Path) -> list[dict]:
    """Моно WAV → списокturns [{speaker: 'SPEAKER_00'|'SPEAKER_01', start_ms, end_ms}]
    в порядке времени. pyannote 4.x возвращает DiarizeOutput (.speaker_diarization —
    Annotation); 3.x возвращал Annotation напрямую — поддерживаем оба."""
    pipeline = _ensure_pipeline()
    result = pipeline(str(wav_path))
    annotation = getattr(result, "speaker_diarization", result)
    turns: list[dict] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        start_ms = int(turn.start * 1000)
        end_ms = int(turn.end * 1000)
        if end_ms - start_ms < 800:
            continue  # короткие транзы ломают ASR (n_fft=320 < сэмплов) и неинформативны
        turns.append({
            "speaker": str(speaker),
            "start_ms": start_ms,
            "end_ms": end_ms,
        })
    turns.sort(key=lambda t: t["start_ms"])
    return turns


AGENT_SPEECH_MARKERS = re.compile(
    r"(компан\w+ |меня зовут|представля\w+|предлагаю|чем могу|наш\w* (продукт|сервис|услуг)"
    r"|бесплатн|демонстрац|давайте я покажу|у нас есть|готов\w+ (предложить|рассказать)"
    r"|я звоню (к вам|вам) с предложением)",
    re.I,
)

# Приветствия оператора — более надёжный сигнал для авто-flip стерео (DoD М3 §1):
# звучат в первых репликах, клиент их не произносит
GREETING_MARKERS = re.compile(
    r"(добр\w+ день|здравству\w+|слушаю|меня зовут|чем могу|готов\w+ помочь"
    r"|вы позвонили в|как я могу (вам )?помочь|компан\w+)",
    re.I,
)


# Порог голосовой идентификации агента: откалиброван на golden-эталоне
# (wespeaker, 16 кГц): same mean 0.60 / diff max 0.56 → 0.58, accuracy 0.77.
# Отчёт: data/datasets/golden/voiceprint_calibration.json; скрипт —
# core/scripts/calibrate_voiceprint.py. Консервативнее текстовых маркеров:
# голос только перебивает их при уверенном совпадении.
VOICEPRINT_THRESHOLD = 0.58


def channel_role_score(text: str) -> int:
    """Сколько агентских маркеров (приветствие + продающие) в тексте канала."""
    return len(GREETING_MARKERS.findall(text or "")) + len(AGENT_SPEECH_MARKERS.findall(text or ""))


def decide_channel_roles(
    head_texts: dict[str, str], channels_map: dict[str, str] | None
) -> tuple[dict[str, str] | None, str]:
    """Runtime-решение авто-flip стерео по текстам голов каналов (doc 02 §2.3 п.1,
    DoD М3 §1). head_texts: {"0": текст первых секунд ch0, "1": ch1}.

    Возвращает (карта ролей, статус): by_markers — роли определены текстом
    (карта коннектора не содержала agent); auto_flipped — противоречат карте,
    перевёрнуты; confirmed — совпали с картой; from_connector — маркеров нет,
    доверяем коннектору; no_map — карты нет. Статус пишется в ключ "_status"
    карты. Чистая функция — покрыта тестами без модели."""
    if not channels_map or not (channels_map.get("0") and channels_map.get("1")):
        return channels_map, "no_map"
    s0 = channel_role_score(head_texts.get("0", ""))
    s1 = channel_role_score(head_texts.get("1", ""))
    if s0 == s1:
        return dict(channels_map), "from_connector"
    detected_agent = "0" if s0 > s1 else "1"
    map_agent = (
        "0" if channels_map.get("0") == "agent"
        else "1" if channels_map.get("1") == "agent"
        else None
    )
    if map_agent == detected_agent:
        new_map = dict(channels_map)
        new_map["_status"] = "confirmed"
        return new_map, "confirmed"
    new_map = {
        "0": "agent" if detected_agent == "0" else "client",
        "1": "agent" if detected_agent == "1" else "client",
    }
    new_map["_status"] = "auto_flipped" if map_agent is not None else "by_markers"
    return new_map, new_map["_status"]


def cosine(a: list[float], b: list[float]) -> float:
    """Косинусная близость векторов-списков (0.0 при пустых/разной длины)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def voice_agent_speaker(
    speaker_vectors: dict[str, list[float]] | None,
    agent_voices: dict[str, list[float]] | None,
    threshold: float = VOICEPRINT_THRESHOLD,
) -> str | None:
    """Спикер, чей усреднённый голос совпал с отпечатком агента (DoD М3 §2.1).
    None — отпечатков нет или совпадений нет. Чистая функция."""
    if not speaker_vectors or not agent_voices:
        return None
    best_spk: str | None = None
    best_score = threshold
    for spk, vec in speaker_vectors.items():
        for voice in agent_voices.values():
            sim = cosine(vec, voice)
            if sim >= best_score:
                best_spk, best_score = spk, sim
    return best_spk


def pick_agent_speaker(
    speaker_texts: dict[str, str], first_speaker: str | None = None
) -> str | None:
    """Выбор агента по маркерам продающей речи (чистая функция, тесты без модели).
    text_score важнее порядка; при равенстве — первый активный."""
    if not speaker_texts:
        return None
    scores = {
        spk: len(AGENT_SPEECH_MARKERS.findall(text or ""))
        for spk, text in speaker_texts.items()
    }
    best = max(scores, key=lambda s: scores[s])
    if scores[best] > 0:
        return best
    return first_speaker


def assign_roles(
    turns: list[dict],
    texts_by_speaker: dict[str, str] | None,
    speaker_vectors: dict[str, list[float]] | None = None,
    agent_voices: dict[str, list[float]] | None = None,
    voice_threshold: float = VOICEPRINT_THRESHOLD,
) -> dict[str, str]:
    """Возвращает карту {сырой спикер: роль} (agent/client). Не мутирует turns.
    Приоритет: совпадение голоса с отпечатком агента (DoD М3 §2.1, ≥ threshold) →
    маркеры продающей речи → первый активный. Прочие спикеры → client."""
    speakers_by_first: dict[str, int] = {}
    for t in turns:
        speakers_by_first.setdefault(t["speaker"], t["start_ms"])
    first_speaker = next(iter(speakers_by_first), None)

    agent = voice_agent_speaker(speaker_vectors, agent_voices, voice_threshold)
    if agent is None:
        agent = pick_agent_speaker(texts_by_speaker or {}, first_speaker)
    mapping = {s: ("agent" if s == agent else "client") for s in speakers_by_first}
    for t in turns:
        t["speaker"] = mapping.get(t["speaker"], "client")
    return mapping
