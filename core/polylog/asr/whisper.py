"""Whisper ASR-бэкенд (OpenAI, MIT) — для тяжёлых по акустике записей
(полевые продажи с телефона: улица, домофонный динамик), где GigaAM,
обученный на телефонной речи, упирается в границу домена.

Модель: openai/whisper-large-v3-turbo (809M, fp16 на GPU). Роли — та же
pyannote-диаризация, что у GigaAM (транзы → куски ≤28 c → текст чанка).
Word-timestamps у turbo шумные, поэтому реплика = текст куска (грубее по
паузам, но устойчиво). Регистрируется в реестре как whisper-large-v3-turbo.
"""

from __future__ import annotations

import logging
import os
import wave
from pathlib import Path

from polylog.asr.base import AsrBackendError, Utterance

log = logging.getLogger("polylog.asr.whisper")

MAX_CHUNK_SEC = 28.0
_model_cache: dict[str, tuple] = {}


def _load(model_name: str):
    key = f"{model_name}@{os.environ.get('POLYLOG_WHISPER_DEVICE', '')}"
    if key not in _model_cache:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

        device = os.environ.get("POLYLOG_WHISPER_DEVICE") or (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        dtype = torch.float16 if device == "cuda" else torch.float32
        log.info("whisper: загрузка %s (device=%s)…", model_name, device)
        processor = AutoProcessor.from_pretrained(model_name)
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_name, torch_dtype=dtype)
        model = model.to(device)
        _model_cache[key] = (processor, model, device)
    return _model_cache[key]


def chunk_asr_text(processor, model, device, chunk_path: Path) -> str:
    """Текст чанка (PCM16 WAV 16 кГц) через processor+generate."""
    import numpy as np
    import torch

    with wave.open(str(chunk_path), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = samples.astype("float32") / 32768.0
    if rate != 16_000:
        n_out = int(round(len(audio) * 16_000 / rate))
        idx = np.arange(n_out, dtype=float) * rate / 16_000
        left = np.clip(idx.astype(int), 0, len(audio) - 1)
        frac = idx - left
        audio = (audio[left] * (1 - frac) + audio[np.clip(left + 1, 0, len(audio) - 1)] * frac)
    inputs = processor(audio, sampling_rate=16_000, return_tensors="pt")
    features = inputs.input_features.to(device=device, dtype=next(model.parameters()).dtype)
    with torch.no_grad():
        generated = model.generate(features, return_timestamps=True)
    return processor.batch_decode(generated, skip_special_tokens=True)[0].strip()


class WhisperBackend:
    def __init__(self, model_name: str = "openai/whisper-large-v3-turbo") -> None:
        self.model_name = model_name
        self.id = f"whisper-{model_name.removeprefix('openai/whisper-')}"
        _load(model_name)  # ранняя проверка доступности модели/устройства

    def transcribe(
        self,
        wav_path: Path,
        channels_map: dict[str, str] | None = None,
        hints: dict | None = None,
    ) -> list[Utterance]:
        from polylog.asr.gigaam import GigaAMBackend
        from polylog.media.normalize import ensure_ffmpeg_on_path

        ensure_ffmpeg_on_path()
        if not wav_path.is_file():
            raise AsrBackendError(f"аудио не найдено: {wav_path}")
        channels, rate, _frames = GigaAMBackend._probe(wav_path)

        if channels == 2 and channels_map:
            out: list[Utterance] = []
            with tempfile_dir() as td:
                for ch, role_key in enumerate(("0", "1")):
                    role = (channels_map or {}).get(role_key, "unknown")
                    mono = td / f"ch{ch}.wav"
                    GigaAMBackend._extract_channel(wav_path, ch, mono)
                    out.extend(self._transcribe_stream(mono, speaker=role))
            return sorted(out, key=lambda u: u.start_ms)

        from polylog.asr import diarize

        if channels == 1 and diarize.available():
            return self._transcribe_diarized(wav_path)

        return self._transcribe_stream(wav_path, speaker="unknown")

    def _transcribe_diarized(self, wav_path: Path) -> list[Utterance]:
        """pyannote-транзы → куски ≤28 c → текст чанка = реплика с ролью."""
        from polylog.asr import diarize
        from polylog.asr.gigaam import GigaAMBackend, turn_chunks

        processor, model, device = _load(self.model_name)
        turns = diarize.diarize(wav_path)
        if not turns:
            return self._transcribe_stream(wav_path, speaker="unknown")

        role_map = diarize.assign_roles(turns, None)  # без текстов: голос/порядок недоступны — первый активный
        utts: list[Utterance] = []
        with tempfile_dir() as td:
            td = Path(td)  # TemporaryDirectory.__enter__ даёт str на 3.13
            for i, turn in enumerate(turns):
                for j, (a, b) in enumerate(turn_chunks(turn["start_ms"], turn["end_ms"], MAX_CHUNK_SEC)):
                    chunk = td / f"turn_{i:03d}_{j:02d}.wav"
                    GigaAMBackend._cut(wav_path, a / 1000, b / 1000, chunk)
                    try:
                        text = chunk_asr_text(processor, model, device, chunk)
                    except Exception as e:  # noqa: BLE001 — пустой/тихий кусок
                        log.warning("whisper чанк %s: %s", chunk.name, e)
                        continue
                    if text:
                        utts.append(Utterance(
                            speaker=role_map.get(turn["speaker"], "client"),
                            start_ms=a, end_ms=b, text=text,
                        ))
        return utts

    def _transcribe_stream(self, wav_path: Path, speaker: str) -> list[Utterance]:
        """Без диаризации: весь файл кусками ≤28 c, спикер фиксирован."""
        from polylog.asr.gigaam import GigaAMBackend, turn_chunks

        processor, model, device = _load(self.model_name)
        channels, rate, frames = GigaAMBackend._probe(wav_path)
        duration_ms = int(frames / rate * 1000) if rate else 0
        utts: list[Utterance] = []
        with tempfile_dir() as td:
            td = Path(td)  # TemporaryDirectory.__enter__ даёт str на 3.13
            for j, (a, b) in enumerate(turn_chunks(0, duration_ms, MAX_CHUNK_SEC)):
                chunk = td / f"chunk_{j:02d}.wav"
                GigaAMBackend._cut(wav_path, a / 1000, b / 1000, chunk)
                try:
                    text = chunk_asr_text(processor, model, device, chunk)
                except Exception as e:  # noqa: BLE001
                    log.warning("whisper чанк %s: %s", chunk.name, e)
                    continue
                if text:
                    utts.append(Utterance(speaker=speaker, start_ms=a, end_ms=b, text=text))
        return utts


def tempfile_dir():
    import tempfile

    return tempfile.TemporaryDirectory(prefix="polylog-whisper-")
