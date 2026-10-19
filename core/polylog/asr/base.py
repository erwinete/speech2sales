"""Контракт ASR-бэкенда (doc 02 §2.4) и реестр с ленивым созданием."""

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class AsrBackendError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start_ms: int
    end_ms: int
    conf: float | None = None


@dataclass
class Utterance:
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)
    conf: float | None = None
    raw_text: str | None = None


class AsrBackend(Protocol):
    id: str

    def transcribe(
        self, wav_path: Path, channels_map: dict[str, str] | None = None
    ) -> list[Utterance]:
        """wav_path — нормализованный 16 кГц PCM WAV (doc 02 §2.1).
        channels_map — {"0": "agent", "1": "client"} из коннектора/диаризации."""
        ...


def wav_duration_sec(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        frames, rate = w.getnframes(), w.getframerate()
    return frames / rate if rate else 0.0


_FACTORIES: dict[str, callable] = {}


def _register(name: str, factory: callable) -> None:
    _FACTORIES[name] = factory


def _stub_factory() -> AsrBackend:
    from polylog.asr.stub import StubAsrBackend

    return StubAsrBackend()


def _gigaam_factory() -> AsrBackend:
    from polylog.asr.gigaam import GigaAMBackend

    return GigaAMBackend()


def _gigaam_ctc_factory() -> AsrBackend:
    from polylog.asr.gigaam import GigaAMBackend

    return GigaAMBackend(model_name="v3_e2e_ctc")


def _tone_factory() -> AsrBackend:
    from polylog.asr.tone import ToneBackend

    return ToneBackend()


def _whisper_turbo_factory() -> AsrBackend:
    from polylog.asr.whisper import WhisperBackend

    return WhisperBackend()


_register("stub", _stub_factory)
_register("gigaam-v3-rnnt", _gigaam_factory)
_register("gigaam-v3-e2e-rnnt", _gigaam_factory)
_register("gigaam-v3-ctc", _gigaam_ctc_factory)
_register("gigaam-v3-e2e-ctc", _gigaam_ctc_factory)
_register("t-one", _tone_factory)
_register("whisper-large-v3-turbo", _whisper_turbo_factory)


def get_backend(name: str) -> AsrBackend:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise AsrBackendError(
            f"неизвестный ASR-бэкенд {name!r}; доступно: {sorted(_FACTORIES)}"
        )
    return factory()
