"""Risk-контур (doc 08 §1): scorecard-холодный старт → CatBoost (после исходов)."""

from typing import Any

from polylog.risk.scorecard import SCORECARD_VERSION, AccountFeatures, scorecard

__all__ = ["AccountFeatures", "SCORECARD_VERSION", "scorecard", "risk_for_contact"]


async def risk_for_contact(session, org_id, contact_id) -> dict[str, Any] | None:
    """Сборка фич контакта из БД → scorecard (doc 08 §1 features_company, v0 по контактам)."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from polylog.models.calls import Call, Objection, Score
    from polylog.models.enums import CallState

    calls = (
        (
            await session.execute(
                select(Call)
                .where(Call.org_id == org_id, Call.contact_id == contact_id)
                .order_by(Call.started_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    if not calls:
        return None

    last = calls[0].started_at
    if last.tzinfo is None:  # sqlite возвращает naive
        last = last.replace(tzinfo=UTC)
    days_silence = max(0, (datetime.now(UTC) - last).days)
    answered = [c for c in calls if c.duration_sec and c.duration_sec > 5]
    unanswered_ratio = 1 - len(answered) / len(calls) if calls else 0.0

    call_ids = [c.id for c in calls]
    objections = (
        (
            await session.execute(
                select(Objection).where(Objection.call_id.in_(call_ids))
            )
        )
        .scalars()
        .all()
    )
    handled = sum(1 for o in objections if o.response_status == "handled_success")
    unhandled_ratio = 1 - handled / len(objections) if objections else 0.0

    scores = (
        await session.execute(
            select(Score.total).where(Score.call_id.in_(call_ids))
        )
    ).scalars().all()
    avg_score = float(sum(scores) / len(scores)) if scores else None

    features = AccountFeatures(
        days_silence=days_silence,
        unanswered_ratio=round(unanswered_ratio, 3),
        unhandled_ratio=round(unhandled_ratio, 3),
        avg_score=round(avg_score, 1) if avg_score is not None else None,
        chain_depth=len(calls),
    )
    # Predictive-модель (doc 08 §1): при N>=30 исходов и обученном CatBoost —
    # она; иначе детерминированный scorecard (холодный старт)
    from polylog.risk import model as risk_model

    trained = risk_model.predict(features)
    if trained is not None:
        trained["features"] = {
            "calls_total": len(calls),
            "objections_total": len(objections),
            "calls_processed_done": sum(1 for c in calls if c.state == CallState.done.value),
        }
        return trained

    result = scorecard(features)
    result["features"] = {
        "calls_total": len(calls),
        "objections_total": len(objections),
        "calls_processed_done": sum(1 for c in calls if c.state == CallState.done.value),
    }
    return result
