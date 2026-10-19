"""GigaAM-v3 адаптер (Salute Developers, MIT) — реальный ASR-бэкенд.

Стратегия:
- модель: `v3_e2e_rnnt` (e2e = пунктуация + нормализация текста);
- `model.transcribe()` принимает аудио ≤ 25 c — режем поток на чанки ≤ 20 c
  (wave-модулем, без ffmpeg), word_timestamps=True → сборка реплик по паузам;
- стерео (двухканальная телефония): транскрибируем каждый канал отдельно,
  роли из channels_map (канальный подход, doc 02 §2.3) — без диаризации;
- RNNT не даёт простых per-token confident'ов → conf=None (avg_conf None).

T-one (doc 02 §2.2) на Windows не ставится (KenLM) — запускается в контейнере
стенда; адаптер tone.py оставлен с ленивым импортом.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from polylog.asr.base import AsrBackendError, Utterance, Word

log = logging.getLogger("polylog.asr.gigaam")

MAX_CHUNK_SEC = 20.0
UTTERANCE_GAP_MS = 600
# Голова канала для runtime-авто-flip (DoD М3 §1): приветствие агента звучит
# в первых секундах; 20 c = предел чанка GigaAM
FLIP_HEAD_SEC = 20.0


def chunk_bounds(duration_sec: float, max_chunk: float = MAX_CHUNK_SEC) -> list[tuple[float, float]]:
    """Границы чанков ≤ max_chunk (чистая функция — покрыта тестом без модели)."""
    if duration_sec <= 0:
        return []
    n = int(duration_sec / max_chunk) + (1 if duration_sec % max_chunk else 0)
    return [(round(i * max_chunk, 3), round(min((i + 1) * max_chunk, duration_sec), 3)) for i in range(n)]


def words_to_utterances(words: list[Word], gap_ms: int = UTTERANCE_GAP_MS, speaker: str = "unknown") -> list[Utterance]:
    """Сборка реплик из слов по паузам (чистая функция)."""
    out: list[Utterance] = []
    cur: list[Word] = []
    for w in words:
        if cur and w.start_ms - cur[-1].end_ms >= gap_ms:
            out.append(_mk_utt(cur, speaker))
            cur = []
        cur.append(w)
    if cur:
        out.append(_mk_utt(cur, speaker))
    return out


def turn_chunks(start_ms: int, end_ms: int, max_chunk: float = MAX_CHUNK_SEC) -> list[tuple[int, int]]:
    """Транз диаризации → подсекции ≤ max_chunk (GigaAM ест ≤20 c), абсолютные
    мс. Чистая функция: длинные монологи (полевые записи!) не должны падать."""
    duration_sec = max(0.0, (end_ms - start_ms) / 1000)
    return [
        (start_ms + int(cs * 1000), start_ms + int(ce * 1000))
        for cs, ce in chunk_bounds(duration_sec, max_chunk)
    ]


def _mk_utt(words: list[Word], speaker: str) -> Utterance:
    return Utterance(
        speaker=speaker,
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        text=" ".join(w.text for w in words).strip(),
        words=words,
        conf=None,
    )


def _mk_utterance(words: list[Word], speaker: str) -> Utterance:
    return Utterance(
        speaker=speaker,
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        text=" ".join(w.text for w in words).strip(),
        words=words,
        conf=None,
    )


class GigaAMBackend:
    id = "gigaam-v3-e2e-rnnt"

    def __init__(
        self,
        model_name: str = "v3_e2e_rnnt",
        download_root: str | None = None,
        device: str | None = None,
    ) -> None:
        try:
            import gigaam
        except ImportError as e:  # pragma: no cover
            raise AsrBackendError(
                "gigaam не установлен: pip install torch torchaudio (CPU) + "
                "gigaam из GitHub salute-developers/GigaAM (см. doc 06 §6)"
            ) from e
        if device is None:
            device = "cuda" if __import__("torch").cuda.is_available() else "cpu"
        self.id = f"gigaam-{model_name}"
        self._model = gigaam.load_model(
            model_name,
            fp16_encoder=(device != "cpu"),
            device=device,
            download_root=download_root or os.environ.get("POLYLOG_MODEL_DIR"),
        )

    def transcribe(
        self,
        wav_path: Path,
        channels_map: dict[str, str] | None = None,
        hints: dict | None = None,
    ) -> list[Utterance]:
        # gigaam сам вызывает ffmpeg через subprocess — PATH должен быть готов
        from polylog.media.normalize import ensure_ffmpeg_on_path

        ensure_ffmpeg_on_path()
        if not wav_path.is_file():
            raise AsrBackendError(f"аудио не найдено: {wav_path}")
        try:
            channels, rate, _frames = self._probe(wav_path)
        except wave.Error as e:
            raise AsrBackendError(f"не читается WAV: {e}") from e

        if channels == 2 and channels_map:
            # канальный подход: каждый канал — отдельный спикер
            out: list[Utterance] = []
            with tempfile.TemporaryDirectory(prefix="polylog-asr-") as td:
                for ch, role_key in enumerate(("0", "1")):
                    role = (channels_map or {}).get(role_key, "unknown")
                    mono = Path(td) / f"ch{ch}.wav"
                    self._extract_channel(wav_path, ch, mono)
                    out.extend(
                        self._transcribe_stream(mono, speaker=role, channel_offset=ch)
                    )
            return sorted(out, key=lambda u: u.start_ms)

        # моно + включённая диаризация: pyannote делит на спикеров,
        # каждый turn транскрибируется отдельно (doc 02 §2.3 механизм 2)
        from polylog.asr import diarize

        if channels == 1 and diarize.available():
            return self._transcribe_diarized(
                wav_path, agent_voices=(hints or {}).get("agent_voices")
            )

        return self._transcribe_stream(wav_path, speaker="unknown", channel_offset=None)

    def prepare_channels(
        self, wav_path: Path, channels_map: dict[str, str] | None
    ) -> tuple[dict[str, str] | None, str | None]:
        """Runtime-валидация карты каналов — авто-flip (doc 02 §2.3 п.1, DoD М3 §1).
        Голова каждого канала (FLIP_HEAD_SEC) транскрибируется, роли предлагает
        decide_channel_roles по маркерам агентской речи. Пайплайн вызывает ДО
        transcribe и сохраняет обновлённую карту (статус в ключе "_status") и
        роли. Ошибка валидации не должна ронять обработку — вызывающий ловит."""
        from polylog.asr.diarize import decide_channel_roles
        from polylog.media.normalize import ensure_ffmpeg_on_path

        ensure_ffmpeg_on_path()
        try:
            channels, rate, frames = self._probe(wav_path)
        except (wave.Error, OSError) as e:
            log.warning("prepare_channels: WAV не читается: %s", e)
            return channels_map, None
        if channels != 2 or not channels_map:
            return channels_map, None

        duration = frames / rate if rate else 0.0
        head_sec = min(FLIP_HEAD_SEC, duration) if duration > 0 else FLIP_HEAD_SEC
        head_texts: dict[str, str] = {}
        with tempfile.TemporaryDirectory(prefix="polylog-flip-") as td:
            for ch in ("0", "1"):
                mono = Path(td) / f"ch{ch}.wav"
                self._extract_channel(wav_path, int(ch), mono)
                head = Path(td) / f"head{ch}.wav"
                self._cut(mono, 0.0, head_sec, head)
                words = self._transcribe_chunk(head, start_ms=0)
                head_texts[ch] = " ".join(w.text for w in words)
        new_map, status = decide_channel_roles(head_texts, channels_map)
        from polylog.asr.diarize import channel_role_score

        log.info(
            "prepare_channels: %s (маркеры ch0=%d ch1=%d)",
            status,
            channel_role_score(head_texts.get("0", "")),
            channel_role_score(head_texts.get("1", "")),
        )
        return new_map, status

    def _transcribe_diarized(
        self, wav_path: Path, agent_voices: dict[str, list[float]] | None = None
    ) -> list[Utterance]:
        """pyannote-диаризация → по спикер-транзам режем чанки → слова → реплики.
        Роль агента выбирается ПО МАРКЕРАМ РЕЧИ (кто предлагает/представляется),
        а не по порядку — устойчивее, чем «первый говоривший»."""
        from polylog.asr.diarize import assign_roles, diarize

        turns = diarize(wav_path)
        if not turns:
            return self._transcribe_stream(wav_path, speaker="unknown", channel_offset=None)

        words: list[Word] = []
        with tempfile.TemporaryDirectory(prefix="polylog-asr-") as td:
            for i, turn in enumerate(turns):
                # транз может быть длиннее 20 c (монолог на полевой записи) —
                # режем на подсекции, иначе GigaAM падает "Too long wav file"
                for j, (abs_start_ms, abs_end_ms) in enumerate(turn_chunks(turn["start_ms"], turn["end_ms"])):
                    chunk = Path(td) / f"turn_{i:03d}_{j:02d}.wav"
                    self._cut(wav_path, abs_start_ms / 1000, abs_end_ms / 1000, chunk)
                    turn_words = self._transcribe_chunk(chunk, start_ms=abs_start_ms)
                    for w in turn_words:
                        w.speaker_tag = turn["speaker"]  # сырой спикер pyannote
                    words.extend(turn_words)

        # роль агента — по тексту: у кого маркеров продающей речи больше;
        # при включённых voiceprintах голос агента имеет приоритет (DoD М3 §2.1)
        texts_by_speaker: dict[str, str] = {}
        for w in words:
            texts_by_speaker.setdefault(w.speaker_tag, "")
            texts_by_speaker[w.speaker_tag] += " " + w.text

        speaker_vectors = None
        if agent_voices:
            try:
                from polylog.asr.voiceprint import speaker_embeddings

                speaker_vectors = speaker_embeddings(wav_path, turns)
            except Exception as e:  # noqa: BLE001 — эмбеддинги не должны ронять ASR
                log.warning("voiceprint-подсказка недоступна: %s", e)

        role_map = assign_roles(
            turns,
            texts_by_speaker,
            speaker_vectors=speaker_vectors,
            agent_voices=agent_voices,
        )

        # группировка слов в реплики: смена сырого спикера ИЛИ пауза ≥ 600 мс
        utterances: list[Utterance] = []
        current: list[Word] = []
        for w in words:
            new_turn = current and w.speaker_tag != current[-1].speaker_tag
            if current and (new_turn or w.start_ms - current[-1].end_ms >= 600):
                utterances.append(_mk_utt(current, role_map.get(current[-1].speaker_tag, "client")))
                current = []
            current.append(w)
        if current:
            utterances.append(_mk_utt(current, role_map.get(current[-1].speaker_tag, "client")))
        return utterances


    def _transcribe_stream(self, wav_path: Path, speaker: str, channel_offset: int | None) -> list[Utterance]:
        with wave.open(str(wav_path), "rb") as w:
            rate, frames = w.getframerate(), w.getnframes()
        duration = frames / rate if rate else 0.0
        words: list[Word] = []
        with tempfile.TemporaryDirectory(prefix="polylog-asr-") as td:
            for start, end in chunk_bounds(duration):
                chunk = Path(td) / f"chunk_{start:.2f}.wav"
                self._cut(wav_path, start, end, chunk)
                words.extend(self._transcribe_chunk(chunk, start_ms=int(start * 1000)))
        return words_to_utterances(words, speaker=speaker)

    def _transcribe_chunk(self, chunk_path: Path, start_ms: int) -> list[Word]:
        try:
            result = self._model.transcribe(str(chunk_path), word_timestamps=True)
        except Exception as e:  # noqa: BLE001 — пустой чанк/тишина не должны ронять пайплайн
            if "empty" in str(e).lower():
                return []
            raise AsrBackendError(f"GigaAM transcribe failed: {e}") from e
        raw_words = getattr(result, "words", None) or []
        out: list[Word] = []
        for w in raw_words:
            out.append(
                Word(
                    text=str(w.text).strip(),
                    start_ms=start_ms + int(w.start * 1000),
                    end_ms=start_ms + int(w.end * 1000),
                    conf=None,
                )
            )
        return [w for w in out if w.text]

    @staticmethod
    def _probe(wav_path: Path) -> tuple[int, int, int]:
        with wave.open(str(wav_path), "rb") as w:
            return w.getnchannels(), w.getframerate(), w.getnframes()

    @staticmethod
    def _cut(wav_path: Path, start_sec: float, end_sec: float, dst: Path) -> None:
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            src.setpos(int(start_sec * params.framerate))
            data = src.readframes(int((end_sec - start_sec) * params.framerate))
        with wave.open(str(dst), "wb") as dst_w:
            dst_w.setparams(params)
            dst_w.writeframes(data)

    @staticmethod
    def _extract_channel(wav_path: Path, channel: int, dst: Path) -> None:
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            raw = src.readframes(params.nframes)
        bytes_per_sample = params.sampwidth
        bytes_per_frame = bytes_per_sample * params.nchannels
        offset = channel * bytes_per_sample
        mono = bytearray()
        for i in range(offset, len(raw) - bytes_per_sample + 1, bytes_per_frame):
            mono += raw[i : i + bytes_per_sample]
        with wave.open(str(dst), "wb") as dst_w:
            dst_w.setnchannels(1)
            dst_w.setsampwidth(params.sampwidth)
            dst_w.setframerate(params.framerate)
            dst_w.writeframes(bytes(mono))

    # совместимость с реестром: параметры по умолчанию
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
