"""NLI-скоринг (ADR-14): multitask_v2 RuBERT из SaaS-тренажёра.

Формат чекпойнта (doc 07 §1.4):
    multitask_model.pt = {model_state: ...} + meta.json (base_model, nli_order)
    архитектура: encoder (AutoModel) + head_nli Linear(768→3) + head_skills Linear(768→19)
    pooling: CLS (last_hidden_state[:, 0]), dropout 0.1
    NLI-порядок v2: 0 Entailment, 1 Contradiction, 2 Neutral

Латентность ~6 мс/пара (batch=1, CPU/GPU) — RUBERT_RETRAIN_REPORT §4.5.
Лицензия весов — вопрос ADR-14/17: локальное использование разрешено, публикация — после юр. ОК.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NLI_LABELS = ("Entailment", "Contradiction", "Neutral")
DEFAULT_MAX_LENGTH = 256


@dataclass
class NliVerdict:
    label: str
    probs: dict[str, float]
    premise: str
    hypothesis: str

    @property
    def answered(self) -> bool:
        """Entailment = ответ по существу (doc 02 §3.2 response classification)."""
        return self.label == "Entailment"


def match_qa_pairs(segments: list[dict], window_ms: int = 30_000) -> list[dict[str, Any]]:
    """Пары «вопрос клиента → ответ агента» (чистая функция, тесты без модели).

    segments: [{idx, speaker, start_ms, end_ms, text}]. Вопрос: текст клиента
    заканчивается '?'. Ответ: первая реплика агента в окне после вопроса.
    """
    pairs: list[dict[str, Any]] = []
    agent_segs = [s for s in segments if s.get("speaker", "").startswith("agent")]
    for seg in segments:
        if not seg.get("speaker", "").startswith("client"):
            continue
        if not seg["text"].rstrip().endswith("?"):
            continue
        response = next(
            (a for a in agent_segs if seg["end_ms"] <= a["start_ms"] <= seg["end_ms"] + window_ms),
            None,
        )
        pairs.append(
            {
                "question": seg["text"],
                "question_start_ms": seg["start_ms"],
                "question_end_ms": seg["end_ms"],
                "answer": response["text"] if response else None,
                "answer_start_ms": response["start_ms"] if response else None,
                "answer_idx": response.get("idx") if response else None,
            }
        )
    return pairs


class NliScorer:
    """Ленивый скорер пар на multitask-чекпойнте. Тяжёлые импорты — внутри."""

    def __init__(self, model_dir: str | Path, max_length: int = DEFAULT_MAX_LENGTH) -> None:
        self.model_dir = Path(model_dir)
        if not (self.model_dir / "multitask_model.pt").is_file():
            raise FileNotFoundError(f"нет чекпойнта в {self.model_dir}")
        self.max_length = max_length
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        meta = json.loads((self.model_dir / "meta.json").read_text(encoding="utf-8"))
        base = meta.get("base_model", "cointegrated/rubert-base-cased-nli-threeway")
        num_nli = int(meta.get("num_nli", 3))
        num_skills = int(meta.get("num_skills", int(meta.get("num_criteria", 19))))

        encoder = AutoModel.from_pretrained(base)
        model = build_multitask(encoder, num_nli, num_skills)
        ckpt = torch.load(str(self.model_dir / "multitask_model.pt"), map_location="cpu", weights_only=False)
        state = ckpt.get("model_state", ckpt)
        model.load_state_dict(state)
        model.eval()
        self._model = model
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        self._torch = torch

    def score(self, premise: str, hypothesis: str) -> NliVerdict:
        return self.score_batch([(premise, hypothesis)])[0]

    def score_batch(self, pairs: list[tuple[str, str]]) -> list[NliVerdict]:
        if not pairs:
            return []
        self._ensure_loaded()
        import torch

        enc = self._tokenizer(
            [p for p, _ in pairs],
            [h for _, h in pairs],
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            nli_logits, _ = self._model(
                input_ids=enc["input_ids"], attention_mask=enc["attention_mask"]
            )
            probs = torch.softmax(nli_logits, dim=-1)
        out: list[NliVerdict] = []
        for i, (p, h) in enumerate(pairs):
            row = probs[i].tolist()
            label = NLI_LABELS[max(range(len(row)), key=lambda k: row[k])]
            out.append(
                NliVerdict(
                    label=label,
                    probs={NLI_LABELS[k]: round(row[k], 4) for k in range(len(row))},
                    premise=p,
                    hypothesis=h,
                )
            )
        return out


def build_multitask(encoder: Any, num_nli: int, num_skills: int) -> Any:
    """Архитектура 1:1 из scripts/train_rubert.py (CLS-pooling, dropout 0.1)."""
    from torch import nn

    class MultiTaskRubertV2(nn.Module):
        def __init__(self, enc):
            super().__init__()
            self.encoder = enc
            h = enc.config.hidden_size
            self.dropout = nn.Dropout(0.1)
            self.head_nli = nn.Linear(h, num_nli)
            self.head_skills = nn.Linear(h, num_skills)

        def forward(self, input_ids=None, attention_mask=None, token_type_ids=None):
            out = self.encoder(
                input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids
            )
            cls = out.last_hidden_state[:, 0]
            return self.head_nli(self.dropout(cls)), self.head_skills(self.dropout(cls))

    return MultiTaskRubertV2(encoder)
