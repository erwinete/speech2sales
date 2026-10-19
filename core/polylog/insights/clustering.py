"""Greedy-кластеризация эмбеддингов возражений (doc 02 §5 objection_pattern).

Без sklearn: leader-clustering по косинусной близости — масштаб МСБ (сотни-тысячи
фраз) покрывает, детерминирован, тестируется чисто. K-means/HDBSCAN — при росте.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return num / (na * nb) if na and nb else 0.0


@dataclass
class PatternCluster:
    center: list[float]
    members: list[int] = field(default_factory=list)  # индексы входных items
    quotes: list[str] = field(default_factory=list)
    types: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        top_types = sorted(self.types.items(), key=lambda kv: -kv[1])
        return {
            "size": len(self.members),
            "member_indices": self.members,
            "quotes": self.quotes[:5],
            "top_types": top_types,
            "dominant_type": top_types[0][0] if top_types else None,
        }


def cluster_items(
    items: list[dict[str, Any]],
    threshold: float = 0.82,
) -> list[PatternCluster]:
    """items: [{vector, text, type}]. Возвращает кластеры (стабильный порядок
    по убыванию размера). Порог 0.82 — эмпирический для телефонного домена;
    настраивается per-org (M3)."""
    clusters: list[PatternCluster] = []
    for idx, item in enumerate(items):
        vec, text = item["vector"], item.get("text", "")
        typ = item.get("type", "other")
        best, best_sim = None, threshold
        for c in clusters:
            sim = cosine(vec, c.center)
            if sim > best_sim:
                best, best_sim = c, sim
        if best is None:
            clusters.append(PatternCluster(center=list(vec), members=[idx],
                                           quotes=[text], types={typ: 1}))
            continue
        # обновление центра — среднее членов (инкрементально)
        n = len(best.members)
        best.center = [
            (c * n + v) / (n + 1) for c, v in zip(best.center, vec, strict=True)
        ]
        best.members.append(idx)
        best.quotes.append(text)
        best.types[typ] = best.types.get(typ, 0) + 1

    clusters.sort(key=lambda c: -len(c.members))
    return clusters
