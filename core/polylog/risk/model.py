"""Predictive-риск (doc 08 §1, M5→M6): scorecard-холодный старт → CatBoost,
когда наберётся N>=30 исходов сделок (won/lost) организации.

Каркас готов заранее: feature builder из тех же фич, что scorecard, +
тренировка/инференс CatBoost, интеграция через risk_for_contact:
  - исходов < N_MIN → scorecard (детерминированный, объяснимый);
  - исходов >= N_MIN и обученная модель есть → CatBoost + фичи-вклады.
CatBoost — опциональная зависимость: не установлен → всегда scorecard.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("polylog.risk.model")

# Исходов (won+lost сделок), после которых включается обучаемая модель
N_MIN_OUTCOMES = int(os.environ.get("POLYLOG_RISK_N_MIN", "30"))
# Файл обученной модели (создаётся scripts/train_risk_model.py)
MODEL_PATH = os.environ.get("POLYLOG_RISK_MODEL_PATH", "data/models/risk_catboost.cbm")

FEATURES = ("days_silence", "unanswered_ratio", "unhandled_ratio", "avg_score", "chain_depth")


def feature_vector(f) -> list[float]:
    """AccountFeatures → числовой вектор (порядок = FEATURES)."""
    avg = f.avg_score
    return [
        float(f.days_silence),
        float(f.unanswered_ratio),
        float(f.unhandled_ratio),
        float(avg) if avg is not None else -1.0,  # нет скора — маркерная константа
        float(f.chain_depth),
    ]


def outcomes_available(session, org_id) -> int:
    """Число закрытых исходов сделок org (won|lost)."""
    from sqlalchemy import func, select

    from polylog.models.graph import Deal

    return (
        session.execute(
            select(func.count())
            .select_from(Deal)
            .where(Deal.org_id == org_id, Deal.status.in_(("won", "lost")))
        )
    ).scalar_one()


def model_ready() -> bool:
    """Есть ли файл обученной модели + CatBoost в окружении."""
    try:
        import catboost  # noqa: F401

        return Path(MODEL_PATH).is_file()
    except ImportError:
        return False


def train(training_rows: list[tuple[list[float], int]], out_path: str = MODEL_PATH) -> dict[str, Any]:
    """Обучение на готовых строках (features, label 1=потеря/0=успех).
    Вызывается скриптом переобучения (ночью, при N>=N_MIN)."""
    try:
        from catboost import CatBoostClassifier
    except ImportError as e:
        raise RuntimeError("catboost не установлен: pip install catboost") from e
    if len(training_rows) < N_MIN_OUTCOMES:
        raise ValueError(f"мало данных: {len(training_rows)} < {N_MIN_OUTCOMES} исходов")
    X = [row[0] for row in training_rows]
    y = [row[1] for row in training_rows]
    model = CatBoostClassifier(iterations=300, depth=5, learning_rate=0.06, verbose=False)
    model.fit(X, y)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_model(out_path)
    return {"samples": len(training_rows), "model_path": out_path}


def predict(f) -> dict[str, Any] | None:
    """Риск 0..100 + SHAP-подобные вклады фич. None — модель недоступна
    (вызывающий откатывается на scorecard). Шейп вкладов совпадает со
    scorecard — UI не различает режимы."""
    if not model_ready():
        return None
    try:
        from catboost import CatBoostClassifier

        model = CatBoostClassifier()
        model.load_model(MODEL_PATH)
        vec = [feature_vector(f)]
        proba = float(model.predict_proba(vec)[0][1])
        # вклады: сдвиг вероятности при обнулении каждой фичи (дёшево и
        # достаточно для UI; точный SHAP — Pool + get_feature_importance)
        contributions: list[float] = []
        base_vec = list(vec[0])
        for i in range(len(FEATURES)):
            perturbed = list(base_vec)
            perturbed[i] = 0.0
            p0 = float(model.predict_proba([perturbed])[0][1])
            contributions.append(proba - p0)
        score = round(proba * 100, 1)
        factors = sorted(
            (
                {
                    "feature": name,
                    "contribution": round(c * 100, 1),
                    "description": f"вклад обученной модели: {c:+.2f}",
                }
                for name, c in zip(FEATURES, contributions, strict=True)
            ),
            key=lambda x: -x["contribution"],
        )
        band = "high" if score >= 55 else "medium" if score >= 25 else "low"
        return {
            "score": score,
            "band": band,
            "factors": factors,
            "model_id": f"catboost@{Path(MODEL_PATH).stem}",
            "calibrated": True,
        }
    except Exception as e:  # noqa: BLE001 — любая ошибка модели → фолбэк
        log.warning("catboost-инференс не удался, откат на scorecard: %s", e)
        return None
