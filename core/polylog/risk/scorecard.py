"""Risk-scorecard M5 (doc 08 §1): холодный старт риск-модели уровня компании/контакта.

Scorecard — детерминированная карта весов по бакетированным фичам (без ML);
CatBoost+SHAP включается после N≥30 исходов org (doc 08 §1, M5). Факторы
выдаются в том же шейпе, что SHAP — UI не различает режимы.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCORECARD_VERSION = "scorecard@0.1.0"


@dataclass
class AccountFeatures:
    days_silence: int = 0          # дней с последнего контакта
    unanswered_ratio: float = 0.0  # доля пропущенных (disposition != ANSWERED)
    unhandled_ratio: float = 0.0   # доля возражений без handled_success
    avg_score: float | None = None # средний скор звонков контакта
    chain_depth: int = 0           # число звонков в цепочке


def bucket_days_silence(days: int) -> tuple[float, str]:
    if days <= 3:
        return 0.0, "тишина ≤ 3 дней"
    if days <= 7:
        return 12.0, "тишина 4–7 дней"
    if days <= 14:
        return 20.0, "тишина 8–14 дней"
    return 28.0, f"тишина {days} дней"


def bucket_unanswered(ratio: float) -> tuple[float, str]:
    if ratio >= 0.5:
        return 14.0, f"{int(ratio * 100)}% звонков пропущено"
    if ratio >= 0.25:
        return 7.0, f"{int(ratio * 100)}% пропущено"
    return 0.0, "пропущенных мало"


def bucket_unhandled(ratio: float) -> tuple[float, str]:
    if ratio >= 0.5:
        return 16.0, f"{int(ratio * 100)}% возражений не отработано"
    if ratio > 0:
        return 8.0, f"{int(ratio * 100)}% не отработано"
    return 0.0, "возражения отработаны"


def bucket_avg_score(score: float | None) -> tuple[float, str]:
    if score is None:
        return 10.0, "нет скоров (звонки не обработаны)"
    if score < 40:
        return 14.0, f"низкий скор {score:.0f}"
    if score < 65:
        return 6.0, f"скор {score:.0f}"
    return 0.0, f"скор {score:.0f}"


BUCKETS = (
    ("days_silence", bucket_days_silence),
    ("unanswered_ratio", bucket_unanswered),
    ("unhandled_ratio", bucket_unhandled),
    ("avg_score", bucket_avg_score),
)


def scorecard(f: AccountFeatures) -> dict[str, Any]:
    """0..100 риск (100 = потеря почти неизбежна) + факторы-вклады."""
    total = 0.0
    factors: list[dict[str, Any]] = []
    for name, bucket in BUCKETS:
        value = getattr(f, name)
        contribution, description = bucket(value)
        total += contribution
        factors.append({
            "feature": name,
            "value": value,
            "contribution": contribution,
            "description": description,
        })
    factors.sort(key=lambda x: -x["contribution"])
    score = min(100.0, total)
    band = "high" if score >= 55 else "medium" if score >= 25 else "low"
    return {
        "score": round(score, 1),
        "band": band,
        "factors": factors,
        "model_id": SCORECARD_VERSION,
        "calibrated": False,
    }
