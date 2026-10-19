"""Эмбеддинги (doc 02 §5): USER2-base (deepvk, Apache-2.0) → pgvector.

Бэкенд ленивый (тяжёлые импорты внутри); финальный выбор эмбеддера — бенчмарком
на eval-наборе (Recall@5 ≥ 0.85, doc 02 §9), USER2-base — стартовый дефолт.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("polylog.embeddings")

DEFAULT_MODEL = "deepvk/USER2-base"


class EmbeddingBackend:
    """transformers AutoModel + mean pooling + L2 (без sentence-transformers)."""

    id: str

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if os.environ.get("HF_HOME"):
            os.environ.setdefault("HF_HOME", os.environ["HF_HOME"])
        self.id = f"{model_name}@base"
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModel.from_pretrained(model_name).to(device).eval()
        self._device = device
        self._torch = torch
        dim = self._model.config.hidden_size
        if dim != 768:
            log.warning("размерность эмбеддера %s != 768 (таблица embeddings — halfvec(768))", dim)
        self.dim = dim

    def embed(self, texts: list[str], max_length: int = 512) -> list[list[float]]:
        """Mean pooling по последнему скрытому состоянию + L2-нормализация."""
        import torch

        out: list[list[float]] = []
        batch = 16
        for i in range(0, len(texts), batch):
            chunk = [t[:20000] for t in texts[i : i + batch]]  # защитная обрезка
            enc = self._tokenizer(
                chunk, padding=True, truncation=True, max_length=max_length,
                return_tensors="pt",
            ).to(self._device)
            with torch.no_grad():
                hidden = self._model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            summed = (hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            mean = summed / counts
            normalized = torch.nn.functional.normalize(mean, p=2, dim=1)
            out.extend(normalized.cpu().tolist())
        return out


_backend: EmbeddingBackend | None = None


def get_backend() -> EmbeddingBackend:
    global _backend
    if _backend is None:
        _backend = EmbeddingBackend(
            model_name=os.environ.get("POLYLOG_EMBED_MODEL", DEFAULT_MODEL),
        )
    return _backend


def embed_call_text(segments: list[dict[str, Any]]) -> tuple[list[float], str]:
    """Вектор звонка = среднее эмбеддингов реплик (doc 02 §5: взвешенный пул v0 — простой mean).
    Возвращает (вектор, model_id)."""
    backend = get_backend()
    texts = [s["text"] for s in segments if s.get("text")]
    if not texts:
        raise ValueError("пустой транскрипт")
    vectors = backend.embed(texts)
    n = len(vectors)
    dim = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / n for i in range(dim)]
    norm = sum(x * x for x in mean) ** 0.5
    return [x / norm for x in mean], backend.id
