"""Пакетный расчёт рисков организации (doc 08 §1, B-3): ровно 3 агрегирующих
SQL-запроса на всю выборку контактов вместо N+1. Используется /risks/top,
/contacts/search и periodic.refresh_insights. Возвращает карту
{contact_id: risk-dict} в том же шейпе, что risk_for_contact."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.models.calls import Call, CallMetrics, Objection, Score
from polylog.risk.model import predict as model_predict
from polylog.risk.scorecard import SCORECARD_VERSION, AccountFeatures, scorecard


async def compute_org_risks_batch(
    session: AsyncSession,
    org_id: uuid.UUID,
    contact_ids: list[uuid.UUID] | None = None,
) -> dict[uuid.UUID, dict[str, Any]]:
    """Риски всех контактов организации (или заданного списка) за 3 запроса.

    1. Звонки + средний скор (GROUP BY contact_id).
    2. Возражения (total / unhandled) (GROUP BY contact_id).
    3. Сентимент последнего и первого звонка (тренд, GROUP BY contact_id).
    """
    now = datetime.now(UTC)

    if contact_ids is None:
        contact_ids = list(
            (
                await session.execute(
                    select(Call.contact_id)
                    .where(Call.org_id == org_id, Call.contact_id.is_not(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
    if not contact_ids:
        return {}

    # 1) звонки + скоры
    call_stats = (
        (
            await session.execute(
                select(
                    Call.contact_id,
                    func.count(),
                    func.max(Call.started_at),
                    func.sum(case((Call.duration_sec > 5, 1), else_=0)),
                    func.avg(Score.total),
                )
                .select_from(Call)
                .outerjoin(Score, Score.call_id == Call.id)
                .where(Call.org_id == org_id, Call.contact_id.in_(contact_ids))
                .group_by(Call.contact_id)
            )
        )
        .all()
    )

    # 2) возражения
    obj_stats = (
        (
            await session.execute(
                select(
                    Call.contact_id,
                    func.count(Objection.id),
                    func.sum(case((Objection.response_status != "handled_success", 1), else_=0)),
                )
                .select_from(Call)
                .join(Objection, Objection.call_id == Call.id)
                .where(Call.org_id == org_id, Call.contact_id.in_(contact_ids))
                .group_by(Call.contact_id)
            )
        )
        .all()
    )
    obj_map = {cid: (tot or 0, unhand or 0) for cid, tot, unhand in obj_stats}

    # 3) сентимент по хронологии (тренд = последний − первый)
    sentiment_rows = (
        (
            await session.execute(
                select(Call.contact_id, Call.started_at, CallMetrics.metrics)
                .select_from(Call)
                .join(CallMetrics, CallMetrics.call_id == Call.id)
                .where(
                    Call.org_id == org_id,
                    Call.contact_id.in_(contact_ids),
                    CallMetrics.metrics.is_not(None),
                )
                .order_by(Call.started_at)
            )
        )
        .all()
    )
    sentiment_seq: dict[uuid.UUID, list[float]] = {}
    for cid, _st, metrics in sentiment_rows:
        cs = (metrics or {}).get("client_sentiment")
        if cs is not None and "score" in cs:
            sentiment_seq.setdefault(cid, []).append(float(cs["score"]))

    result: dict[uuid.UUID, dict[str, Any]] = {}
    for cid, cnt, last, answered, avg_sc in call_stats:
        if cnt == 0:
            continue
        total_obj, unhandled = obj_map.get(cid, (0, 0))
        if last is not None and last.tzinfo is None:  # sqlite возвращает naive
            last = last.replace(tzinfo=UTC)
        days_silence = max(0, (now - last).days) if last is not None else 0
        avg = round(float(avg_sc), 1) if avg_sc is not None else None
        feats = AccountFeatures(
            days_silence=days_silence,
            unanswered_ratio=round(1 - (answered or 0) / cnt, 3),
            unhandled_ratio=round(unhandled / total_obj, 3) if total_obj else 0.0,
            avg_score=avg,
            chain_depth=cnt,
        )
        risk = model_predict(feats) or scorecard(feats)
        seq = sentiment_seq.get(cid) or []
        risk["features"] = {
            "calls_total": cnt,
            "objections_total": total_obj,
            "objections_unhandled": unhandled,
            "avg_score": avg,
            "days_silence": days_silence,
            "last_call_at": last.isoformat() if last is not None else None,
            "sentiment_last": seq[-1] if seq else None,
            "sentiment_trend": round(seq[-1] - seq[0], 3) if len(seq) > 1 else None,
            "model_id": risk.get("model_id", SCORECARD_VERSION),
        }
        result[cid] = risk
    return result
