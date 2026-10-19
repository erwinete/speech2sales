"""T-one адаптер (Т-Технологии, Apache-2.0, телефонный домен, streaming).

Ограничение: пакет `tone` ставится через Poetry и тянет KenLM, у которого нет
поддержки Windows — адаптер запускается в Linux-контуре (dev-стенд/docker,
doc 09 §4). На Windows __init__ отдаёт информативную ошибку.

API (README voicekit-team/T-one):
    from tone import StreamingCTCPipeline, read_audio
    pipeline = StreamingCTCPipeline.from_hugging_face()
    result = pipeline.forward_offline(read_audio(path))
"""

from __future__ import annotations

from pathlib import Path

from polylog.asr.base import AsrBackendError, Utterance


class ToneBackend:
    id = "t-one"

    def __init__(self, **_: object) -> None:
        try:
            from tone import StreamingCTCPipeline  # noqa: F401
        except ImportError as e:
            raise AsrBackendError(
                "T-one недоступен на Windows (KenLM): запускать в docker/WSL "
                "(voicekit-team/T-one, Linux). Детали — polylog/asr/README"
            ) from e
        self._pipeline_cls = StreamingCTCPipeline
        self._pipeline = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is None:
            self._pipeline = self._pipeline_cls.from_hugging_face()

    def transcribe(
        self,
        wav_path: Path,
        channels_map: dict[str, str] | None = None,
        hints: dict | None = None,
    ) -> list[Utterance]:
        self._ensure_pipeline()
        raise AsrBackendError(
            "T-one offline-инференс в адаптере будет завершён при подключении "
            "Linux-контура (фразы с таймингами из forward_offline → Utterance)"
        )
