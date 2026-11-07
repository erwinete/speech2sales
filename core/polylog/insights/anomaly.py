"""Детектор аномалий M6 trend-anomaly (V5-04, ТЗ v5.0 §9.1; docs/08 §1):
сравнение метрик последних 7 дней с базовым окном 30 дней — резкие просадки
среднего балла, всплески возражений, рост молчания (пауз) менеджеров.
Инсайты пишутся в periodic.refresh_insights (kind="trend_anomaly")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.models.calls import Call, CallMetrics, Objection, Score
from polylog.models.system import Insight

# Порог срабатывания: относительное отклонение окна 7д от базового окна 30д
DROP_RATIO = 0.85   # средний балл упал более чем на 15%
SPIKE_RATIO = 1.5   # возражений/пауз стало в 1.5 раза больше (на звонок)
MIN_BASELINE_CALLS = 5


async def _window_stats(session: AsyncSession, org_id: uuid.UUID, since: datetime) -> dict[str, Any]:
    calls = (
        (
            await session.execute(
                select(Call.id)
                .where(Call.org_id == org_id, Call.state == "done", Call.started_at >= since)
            )
        )
        .scalars()
        .all()
    )
    n = len(calls)
    if n == 0:
        return {"calls": 0, "avg_score": None, "objections_per_call": 0.0, "pauses_per_call": 0.0}
    avg_score = (
        (
            await session.execute(
                select(func.avg(Score.total)).where(Score.call_id.in_(calls))
            )
        )
        .scalar()
    )
    obj_total = (
        (
            await session.execute(
                select(func.count(Objection.id)).where(Objection.call_id.in_(calls))
            )
        )
        .scalar()
    ) or 0
    pause_total = 0
    metrics_rows = (
        (
            await session.execute(
                select(CallMetrics.metrics).where(CallMetrics.call_id.in_(calls))
            )
        )
        .scalars()
        .all()
    )
    for metrics in metrics_rows:
        pause_total += int((metrics or {}).get("pauses", {}).get("count") or 0)
    return {
        "calls": n,
        "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        "objections_per_call": round(obj_total / n, 2),
        "pauses_per_call": round(pause_total / n, 2),
    }


async def detect_org_anomalies(session: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """Сравнение окна 7 дней с базой 30 дней. Возвращает список аномалий
    {kind, severity, message, payload}; дедуп-ключ — (org, kind, message)."""
    now = datetime.now(UTC)
    recent = await _window_stats(session, org_id, now - timedelta(days=7))
    baseline = await _window_stats(session, org_id, now - timedelta(days=30))
    if recent["calls"] < 3 or baseline["calls"] < MIN_BASELINE_CALLS:
        return []

    anomalies: list[dict[str, Any]] = []
    if baseline["avg_score"] and recent["avg_score"] and recent["avg_score"] < baseline["avg_score"] * DROP_RATIO:
        anomalies.append({
            "kind": "trend_anomaly",
            "severity": "critical",
            "message": f"Средний балл упал: {recent['avg_score']} против {baseline['avg_score']} в базовом окне",
            "payload": {
                "metric": "avg_score", "recent": recent["avg_score"],
                "baseline": baseline["avg_score"],
                "ratio": round(recent["avg_score"] / baseline["avg_score"], 3),
            },
        })
    obj_spike = recent["objections_per_call"] > baseline["objections_per_call"] * SPIKE_RATIO
    if obj_spike and recent["objections_per_call"] > 0:
        anomalies.append({
            "kind": "trend_anomaly",
            "severity": "warning",
            "message": (
                f"Всплеск возражений: {recent['objections_per_call']} на звонок "
                f"против {baseline['objections_per_call']}"
            ),
            "payload": {
                "metric": "objections_per_call", "recent": recent["objections_per_call"],
                "baseline": baseline["objections_per_call"],
                "ratio": round(recent["objections_per_call"] / max(baseline["objections_per_call"], 0.01), 3),
            },
        })
    pause_spike = recent["pauses_per_call"] > baseline["pauses_per_call"] * SPIKE_RATIO
    if pause_spike and recent["pauses_per_call"] > 0:
        anomalies.append({
            "kind": "trend_anomaly",
            "severity": "warning",
            "message": (
                f"Рост молчания: {recent['pauses_per_call']} пауз на звонок "
                f"против {baseline['pauses_per_call']}"
            ),
            "payload": {
                "metric": "pauses_per_call", "recent": recent["pauses_per_call"],
                "baseline": baseline["pauses_per_call"],
                "ratio": round(recent["pauses_per_call"] / max(baseline["pauses_per_call"], 0.01), 3),
            },
        })
    return anomalies


async def refresh_trend_anomalies(session: AsyncSession) -> int:
    """Вставка trend_anomaly-инсайтов (дедуп по message): вызывается из
    periodic.refresh_insights. Возвращает число новых инсайтов."""
    from polylog.graph.service import get_default_org

    org = await get_default_org(session)
    existing = set(
        (
            await session.execute(
                select(Insight.payload).where(
                    Insight.org_id == org.id, Insight.kind == "trend_anomaly", Insight.status == "new"
                )
            )
        )
        .scalars()
        .all()
    )
    seen_messages = {(p or {}).get("message") for p in existing}
    created = 0
    for anomaly in await detect_org_anomalies(session, org.id):
        if anomaly["message"] in seen_messages:
            continue
        session.add(
            Insight(
                org_id=org.id, kind="trend_anomaly", severity=anomaly["severity"],
                payload={"message": anomaly["message"], **anomaly["payload"]},
                generated_by="m6-trend-anomaly",
            )
        )
        created += 1
    return created
