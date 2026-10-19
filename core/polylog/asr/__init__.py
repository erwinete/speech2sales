"""ASR-адаптеры (doc 02 §2.4). Реестр бэкендов с ленивой инициализацией."""

from polylog.asr.base import AsrBackend, AsrBackendError, Utterance, Word, get_backend

__all__ = ["AsrBackend", "AsrBackendError", "Utterance", "Word", "get_backend"]
