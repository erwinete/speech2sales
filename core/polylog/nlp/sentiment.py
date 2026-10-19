"""Сентимент клиента (DoD М2/М3): нормализованный скор −1…+1 по клиентским
репликам на лексиконах правил — без LLM, детерминированно и быстро.

Скор = (позитив − негатив) / max(1, позитив + негатив). Учитываются только
реплики клиента: эмоции оператора («рад помочь») не должны поднимать тон
клиента. Используется в метриках звонка, тренде тональности карточки 360
и как фича будущей CatBoost-модели (doc 08 §1)."""

from __future__ import annotations

import re
from typing import Any

# Позитивные маркеры клиента (согласие, интерес, готовность к шагу)
POSITIVE_MARKERS = re.compile(
    r"(да,? конечно|интересно|давайте|хорошо|отлично|звучит|жду|пришлите|кидайте|"
    r"посмотрим|зайд[её]м|размест[иі]м|актуально|нужно|подходит|согласен|"
    r"спасибо|будет полезно|обязательно посмотрю|созвонимся|давайте созвонимся)",
    re.I,
)
# Негативные маркеры (отказ, недовольство, проблема)
NEGATIVE_MARKERS = re.compile(
    r"(не интересно|не нужно|не актуально|дорого|дороговато|не будем|не хочу|"
    r"не буду|не могу|не нравится|раздражает|не работает|проблема|жалоба|"
    r"хватит|не звони|мимо|не надо|не стоит|разочарован|ужас|плохо|бесполезно)",
    re.I,
)


def sentiment_of_text(text: str) -> tuple[int, int]:
    """(позитивные, негативные) срабатывания маркеров в тексте.
    Негатив приоритетен: «не интересно» не считается позитивом «интересно» —
    позитивные совпадения, пересекающиеся с негативными, отбрасываются."""
    t = text or ""
    neg_spans = [m.span() for m in NEGATIVE_MARKERS.finditer(t)]

    def overlaps_neg(start: int, end: int) -> bool:
        return any(start < ne and ns < end for ns, ne in neg_spans)

    pos = sum(1 for m in POSITIVE_MARKERS.finditer(t) if not overlaps_neg(*m.span()))
    return pos, len(neg_spans)


def client_sentiment(utterances: list[dict]) -> dict[str, Any]:
    """Агрегат по клиентским репликам: {score, positive, negative, client_words}.
    score ∈ [−1; +1]; при ноль маркеров — 0.0 (neutral). utterances — dicts с
    полями speaker/text (как в _segment_dicts пайплайна)."""
    pos = neg = 0
    client_words = 0
    for u in utterances:
        if u.get("speaker") != "client":
            continue
        p, n = sentiment_of_text(u.get("text") or "")
        pos += p
        neg += n
        client_words += len((u.get("text") or "").split())
    score = (pos - neg) / max(1, pos + neg)
    return {
        "score": round(max(-1.0, min(1.0, score)), 3),
        "positive": pos,
        "negative": neg,
        "client_words": client_words,
    }


def sentiment_emoji(score: float | None) -> str:
    """Один глиф для UI: 😊/😐/☹; None или пустая речь → «»."""
    if score is None:
        return ""
    if score > 0.2:
        return "😊"
    if score < -0.2:
        return "☹"
    return "😐"
