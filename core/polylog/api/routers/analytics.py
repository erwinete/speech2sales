"""Роутер аналитики: сводка (расширенная), временные ряды, менеджеры, компании."""  # noqa: E501

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from polylog.api.deps import AuthDep, SessionDep
from polylog.graph.service import get_default_org
from polylog.models.calls import Call, CallMetrics, Objection, Score, Signal, Violation
from polylog.models.enums import CallState

router = APIRouter(prefix="/api/v1", tags=["analytics"])


def _since(days: int, date_from: str | None, date_to: str | None):
    conds_since = datetime.now(UTC) - timedelta(days=days)
    conds = []
    if date_from:
        conds.append(Call.started_at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
    if date_to:
        conds.append(Call.started_at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))
    if not date_from and not date_to:
        conds.append(Call.started_at >= conds_since)
    return conds


@router.get("/stats/summary")
async def stats_summary(
    session: SessionDep,
    _: AuthDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    date_from: str | None = None,
    date_to: str | None = None,
) -> JSONResponse:
    """Сводные KPI дашборда (обратная совместимость + новые поля)."""
    org = await get_default_org(session)
    conds = [Call.org_id == org.id, *_since(days, date_from, date_to)]

    total = (await session.execute(select(func.count()).select_from(Call).where(*conds))).scalar_one()
    done = (
        await session.execute(
            select(func.count()).select_from(Call).where(*conds, Call.state == CallState.done.value)
        )
    ).scalar_one()
    failed = (
        await session.execute(
            select(func.count()).select_from(Call).where(*conds, Call.state == CallState.failed.value)
        )
    ).scalar_one()
    avg_score = (
        await session.execute(
            select(func.avg(Score.total)).join(Call, Call.id == Score.call_id).where(*conds)
        )
    ).scalar_one()
    avg_duration = (
        await session.execute(select(func.avg(Call.duration_sec)).where(*conds))
    ).scalar_one()

    objections = (
        (
            await session.execute(
                select(Objection.type, Objection.response_status)
                .join(Call, Call.id == Objection.call_id)
                .where(*conds)
            )
        )
        .all()
    )
    top_objections_map: dict[str, dict] = {}
    for ty, status in objections:
        d = top_objections_map.setdefault(ty, {"type": ty, "count": 0, "handled_count": 0})
        d["count"] += 1
        if status == "handled_success":
            d["handled_count"] += 1
    top_objections = sorted(top_objections_map.values(), key=lambda x: -x["count"])[:5]

    signals_total = (
        await session.execute(
            select(func.count()).select_from(Signal).join(Call, Call.id == Signal.call_id).where(*conds)
        )
    ).scalar_one()
    violations_total = (
        await session.execute(
            select(func.count()).select_from(Violation).join(Call, Call.id == Violation.call_id).where(*conds)
        )
    ).scalar_one()

    # talk_ratio и сентимент из метрик
    metrics_rows = (
        (
            await session.execute(
                select(CallMetrics.metrics)
                .join(Call, Call.id == CallMetrics.call_id)
                .where(*conds)
            )
        )
        .scalars()
        .all()
    )
    talk_ratios, sentiments = [], []
    for m in metrics_rows:
        tr = (m or {}).get("talk_ratio", {}).get("agent")
        if tr is not None:
            talk_ratios.append(tr)
        cs = (m or {}).get("client_sentiment", {}).get("score")
        if cs is not None:
            sentiments.append(cs)

    return JSONResponse({
        "period_days": days,
        "total_calls": total,
        "done_calls": done,
        "failed_calls": failed,
        "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
        "avg_duration_sec": round(float(avg_duration), 1) if avg_duration is not None else None,
        "avg_talk_ratio_agent": round(sum(talk_ratios) / len(talk_ratios), 3) if talk_ratios else None,
        "objections_total": len(objections),
        "objections_handled_ratio": (
            round(sum(d["handled_count"] for d in top_objections_map.values()) / len(objections), 3)
            if objections
            else None
        ),
        "signals_total": signals_total,
        "violations_total": violations_total,
        "top_objections": top_objections,
        "top_signals": [],
        "sentiment_avg": round(sum(sentiments) / len(sentiments), 3) if sentiments else None,
    })


@router.get("/analytics/timeseries")
async def timeseries(
    session: SessionDep,
    _: AuthDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    date_from: str | None = None,
    date_to: str | None = None,
) -> JSONResponse:
    """Временные ряды по дням для графиков дашборда."""
    org = await get_default_org(session)
    conds = [Call.org_id == org.id, *_since(days, date_from, date_to)]
    rows = (
        (
            await session.execute(
                select(
                    func.date(Call.started_at),
                    func.count(),
                    func.sum(func.coalesce(Call.state == CallState.done.value, 0)),
                ).where(*conds).group_by(func.date(Call.started_at)).order_by(func.date(Call.started_at))
            )
        )
        .all()
    )
    scores = (
        (
            await session.execute(
                select(func.date(Call.started_at), func.avg(Score.total))
                .select_from(Call)
                .join(Score, Score.call_id == Call.id)
                .where(*conds)
                .group_by(func.date(Call.started_at))
            )
        )
        .all()
    )
    score_map = {str(d): s for d, s in scores}
    obj_rows = (
        (
            await session.execute(
                select(func.date(Call.started_at), func.count())
                .select_from(Call)
                .join(Objection, Objection.call_id == Call.id)
                .where(*conds)
                .group_by(func.date(Call.started_at))
            )
        )
        .all()
    )
    obj_map = {str(d): c for d, c in obj_rows}
    is_pg = session.bind and session.bind.url.get_backend_name().startswith("postgresql")
    sentiment_rows = (
        (
            await session.execute(
                select(func.date(Call.started_at), func.avg(CallMetrics.metrics.op("->>")("client_sentiment")))
                .select_from(Call)
                .join(CallMetrics, CallMetrics.call_id == Call.id)
                .where(*conds)
                .group_by(func.date(Call.started_at))
            )
        )
        .all()
        if is_pg
        else []
    )
    sent_map = {}
    for d, s in sentiment_rows:
        try:
            sent_map[str(d)] = float(s)
        except (TypeError, ValueError):
            continue

    points = []
    for d, total_c, done_c in rows:
        key = str(d)
        points.append({
            "date": key,
            "calls_total": int(total_c or 0),
            "calls_done": int(done_c or 0),
            "avg_score": round(float(score_map[key]), 1) if key in score_map else None,
            "objections_count": obj_map.get(key, 0),
            "handled_ratio": None,
            "sentiment_avg": sent_map.get(key),
        })
    return JSONResponse({"points": points})


@router.get("/analytics/managers")
async def managers(session: SessionDep, _: AuthDep, days: Annotated[int, Query(ge=1, le=365)] = 30) -> JSONResponse:
    """Лидерборд и матрица навыков менеджеров (коучинг РОПа)."""
    from polylog.models.system import User

    org = await get_default_org(session)
    conds = [Call.org_id == org.id, *_since(days, None, None)]
    calls = (
        (await session.execute(select(Call).where(*conds))).scalars().all()
    )
    call_ids = [c.id for c in calls]
    scores_by_call: dict[uuid.UUID, list[float]] = defaultdict(list)
    if call_ids:
        for sc in (
            await session.execute(select(Score).where(Score.call_id.in_(call_ids)))
        ).scalars().all():
            scores_by_call[sc.call_id].append(sc.total)
    metrics_by_call: dict[uuid.UUID, dict] = {}
    if call_ids:
        for m in (
            await session.execute(select(CallMetrics).where(CallMetrics.call_id.in_(call_ids)))
        ).scalars().all():
            metrics_by_call[m.call_id] = m.metrics or {}
    objections_by_call: dict[uuid.UUID, dict] = {}
    if call_ids:
        for o in (
            await session.execute(select(Objection).where(Objection.call_id.in_(call_ids)))
        ).scalars().all():
            d = objections_by_call.setdefault(o.call_id, {"total": 0, "handled": 0})
            d["total"] += 1
            if o.response_status == "handled_success":
                d["handled"] += 1
    violations_by_call: dict[uuid.UUID, int] = defaultdict(int)
    if call_ids:
        for v in (
            await session.execute(select(Violation).where(Violation.call_id.in_(call_ids)))
        ).scalars().all():
            violations_by_call[v.call_id] += 1

    users = (
        (await session.execute(select(User).where(User.org_id == org.id))).scalars().all()
    )
    name_by_id = {u.id: u for u in users}

    # группировка звонков по менеджеру (agent_user_id или внутренний номер)
    per_user: dict[str, dict] = defaultdict(lambda: {"calls": [], "ext": None})
    for c in calls:
        key = str(c.agent_user_id) if c.agent_user_id else None
        ext = None
        if c.direction == "outbound" and c.phone_from and c.phone_from.isdigit() and len(c.phone_from) <= 6:
            ext = c.phone_from
        elif c.direction == "inbound" and c.phone_to and c.phone_to.isdigit() and len(c.phone_to) <= 6:
            ext = c.phone_to
        bucket = per_user[key] if key else per_user[f"ext:{ext}" if ext else f"call:{c.id}"]
        bucket["calls"].append(c)
        if ext and bucket["ext"] is None:
            bucket["ext"] = ext

    items = []
    for key, bucket in per_user.items():
        calls_list = bucket["calls"]
        call_ids_u = [c.id for c in calls_list]
        scores_all = [s for cid in call_ids_u for s in scores_by_call.get(cid, [])]
        obj_total = sum(objections_by_call.get(cid, {}).get("total", 0) for cid in call_ids_u)
        obj_handled = sum(objections_by_call.get(cid, {}).get("handled", 0) for cid in call_ids_u)
        talk_ratios = [
            metrics_by_call[cid].get("talk_ratio", {}).get("agent")
            for cid in call_ids_u
            if metrics_by_call.get(cid, {}).get("talk_ratio", {}).get("agent") is not None
        ]
        questions = [
            metrics_by_call[cid].get("questions", {}).get("agent", 0)
            for cid in call_ids_u
            if metrics_by_call.get(cid)
        ]
        sentiments = [
            metrics_by_call[cid].get("client_sentiment", {}).get("score")
            for cid in call_ids_u
            if metrics_by_call.get(cid, {}).get("client_sentiment", {}).get("score") is not None
        ]
        user_key = key if key and not key.startswith(("ext:", "call:")) else None
        u = name_by_id.get(uuid.UUID(user_key)) if user_key else None
        items.append({
            "user_id": key if u else None,
            "display_name": (u.display_name if u else None)
            or (f"Внутр. номер {bucket['ext']}" if bucket["ext"] else "Без привязки"),
            "agent_ext": bucket["ext"],
            "team_name": u.team_name if u else None,
            "calls_total": len(calls_list),
            "calls_done": sum(1 for c in calls_list if c.state == "done"),
            "avg_score": round(sum(scores_all) / len(scores_all), 1) if scores_all else None,
            "talk_ratio_agent": round(sum(talk_ratios) / len(talk_ratios), 3) if talk_ratios else None,
            "questions_avg": round(sum(questions) / len(questions), 2) if questions else 0.0,
            "objections_total": obj_total,
            "objections_handled_ratio": round(obj_handled / obj_total, 3) if obj_total else None,
            "violations_count": sum(violations_by_call.get(cid, 0) for cid in call_ids_u),
            "sentiment_avg": round(sum(sentiments) / len(sentiments), 3) if sentiments else None,
            "criteria_scores": {},
        })
    items.sort(key=lambda x: -(x["avg_score"] or 0))
    return JSONResponse({"items": items, "total": len(items)})


@router.get("/analytics/stages-funnel")
async def stages_funnel(
    session: SessionDep, _: AuthDep, days: Annotated[int, Query(ge=1, le=365)] = 30
) -> JSONResponse:
    """Воронка стадий диалога (V5-02, ТЗ v5.0 §9.2-2): на каком этапе скрипта
    обрываются звонки — число звонков, достигших каждой из 8 стадий, и средняя
    глубина прохождения."""
    from polylog.nlp.stages import DIALOG_STAGES

    org = await get_default_org(session)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await session.execute(
                select(CallMetrics.metrics)
                .select_from(Call)
                .join(CallMetrics, CallMetrics.call_id == Call.id)
                .where(Call.org_id == org.id, Call.state == "done", Call.started_at >= cutoff)
            )
        )
        .scalars()
        .all()
    )
    reached = {stage: 0 for stage in DIALOG_STAGES}
    calls_with_stages = 0
    depths: list[int] = []
    for metrics in rows:
        stages = (metrics or {}).get("stages") or []
        seen = [s["stage"] for s in stages if s.get("stage") in reached]
        if not seen:
            continue
        calls_with_stages += 1
        depths.append(len(seen))
        for stage in dict.fromkeys(seen):  # уникальные в порядке прохождения
            reached[stage] += 1
    items = [
        {
            "stage": stage,
            "stage_ru": {
                "greeting": "Приветствие", "identification": "Знакомство",
                "qualification": "Квалификация", "presentation": "Презентация",
                "objection_handling": "Возражения", "negotiation": "Торговля",
                "closing": "Закрытие", "goodbye": "Прощание",
            }[stage],
            "calls_reached": reached[stage],
            "conversion": round(reached[stage] / calls_with_stages, 3) if calls_with_stages else 0.0,
        }
        for stage in DIALOG_STAGES
    ]
    return JSONResponse({
        "days": days,
        "calls_analyzed": len(rows),
        "calls_with_stages": calls_with_stages,
        "avg_depth": round(sum(depths) / len(depths), 2) if depths else 0.0,
        "items": items,
    })
