"""Роутер инсайтов: лента, ack/dismiss, кластеры возражений (без блокировки
event loop — B-2), риски топ (без N+1 — B-3), семантический поиск."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from polylog.api.deps import AuthDep, SessionDep
from polylog.graph.service import get_default_org
from polylog.models.system import Insight

router = APIRouter(prefix="/api/v1", tags=["insights"])

# in-memory кэш кластеризации: ключ → (ts, payload)
_clusters_cache: dict[tuple, tuple[float, dict]] = None  # type: ignore[assignment]
_clusters_cache = {}
CLUSTER_TTL_SEC = 600


@router.get("/insights")
async def list_insights(
    session: SessionDep,
    _: AuthDep,
    status_filter: Annotated[str | None, Query(alias="status")] = "new",
    severity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JSONResponse:
    """Лента инсайтов: risk_account и repeat_objection; фильтры status/severity."""
    org = await get_default_org(session)
    conds = [Insight.org_id == org.id]
    if status_filter:
        conds.append(Insight.status == status_filter)
    if severity:
        conds.append(Insight.severity == severity)
    rows = (
        (
            await session.execute(
                select(Insight).where(*conds).order_by(Insight.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return JSONResponse({
        "items": [
            {
                "id": str(i.id),
                "kind": i.kind,
                "severity": i.severity,
                "contact_id": str(i.contact_id) if i.contact_id else None,
                "payload": i.payload,
                "generated_by": i.generated_by,
                "status": i.status,
                "created_at": i.created_at.isoformat(),
            }
            for i in rows
        ]
    })


@router.post("/insights/{insight_id}/{action}")
async def insight_action(insight_id: uuid.UUID, action: str, session: SessionDep, _: AuthDep) -> JSONResponse:
    """ack (принято, уходит из ленты) | dismiss (скрыто)."""
    if action not in ("ack", "dismiss"):
        raise HTTPException(422, "action: ack | dismiss")
    insight = await session.get(Insight, insight_id)
    if insight is None:
        raise HTTPException(404, "инсайт не найден")
    insight.status = "ack" if action == "ack" else "dismiss"
    await session.commit()
    return {"id": str(insight.id), "status": insight.status}


@router.get("/insights/objection-clusters")
async def objection_clusters(
    session: SessionDep,
    _: AuthDep,
    days: Annotated[int, Query(ge=1, le=365)] = 90,
    threshold: Annotated[float, Query(ge=0.5, le=0.99)] = 0.82,
) -> JSONResponse:
    """Кластеры похожих возражений: embeddings в to_thread (B-2), кэш 10 мин."""
    import time

    from polylog.embeddings import get_backend
    from polylog.insights.clustering import cluster_items
    from polylog.models.calls import Call, Objection

    org = await get_default_org(session)
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await session.execute(
                select(
                    Objection.span_text,
                    Objection.type,
                    Objection.call_id,
                    Call.phone_from,
                    Call.phone_to,
                    Call.started_at,
                    Call.direction,
                )
                .join(Call, Call.id == Objection.call_id)
                .where(
                    Call.org_id == org.id,
                    Call.started_at >= since,
                    Call.duration_sec.is_(None) | (Call.duration_sec >= 15),
                )
                .limit(2000)
            )
        )
        .all()
    )
    if not rows:
        return JSONResponse({"period_days": days, "clusters": [], "total": 0})

    max_obj_id = max(r[2] for r in rows)
    cache_key = (str(org.id), days, threshold, str(max_obj_id))
    cached = _clusters_cache.get(cache_key)
    if cached and time.time() - cached[0] < CLUSTER_TTL_SEC:
        return JSONResponse(cached[1])

    def _embed_all(texts: list[str]) -> list[list[float]]:
        backend = get_backend()
        return backend.embed(texts)

    vectors = await asyncio.to_thread(_embed_all, [r[0] for r in rows])
    items = [
        {
            "vector": v,
            "text": txt,
            "type": ty,
            "call_id": str(cid),
            "phone": (pt if direction == "outbound" else pf) or pf or pt,
            "started_at": st.isoformat(),
        }
        for v, (txt, ty, cid, pf, pt, st, direction) in zip(vectors, rows, strict=True)
    ]
    call_info = {it["call_id"]: (it["phone"], it["started_at"]) for it in items}

    def _cluster() -> list[dict]:
        return cluster_items(items, threshold=threshold)

    clusters = await asyncio.to_thread(_cluster)
    out = []
    for c in clusters[:20]:
        d = c.as_dict()
        member_calls = list(dict.fromkeys(items[i]["call_id"] for i in c.members))
        d["calls"] = [
            {"call_id": cid, "phone": call_info[cid][0], "started_at": call_info[cid][1]}
            for cid in member_calls[:8]
        ]
        out.append(d)

    payload = {
        "period_days": days,
        "threshold": threshold,
        "total_objections": len(rows),
        "clusters": out,
    }
    _clusters_cache.clear()
    _clusters_cache[cache_key] = (time.time(), payload)
    return JSONResponse(payload)


@router.get("/risks/top")
async def risks_top(
    session: SessionDep,
    _: AuthDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> JSONResponse:
    """Риск-борд РОПа: пакетный расчёт (B-3), отсортированный по риску."""
    from polylog.risk.batch import compute_org_risks_batch

    org = await get_default_org(session)
    risks = await compute_org_risks_batch(session, org.id)
    items = []
    for cid, r in risks.items():
        items.append({
            "contact_id": str(cid),
            "score": r["score"],
            "band": r["band"],
            "top_factor": r["factors"][0]["description"] if r["factors"] else "",
            "factors": r["factors"][:3],
            "calls_total": (r.get("features") or {}).get("calls_total"),
            "recent_call_ids": [],
        })
    items.sort(key=lambda x: -x["score"])
    return JSONResponse({"items": items[:limit], "total": len(items)})


@router.get("/search/similar")
async def search_similar(
    call_id: uuid.UUID,
    session: SessionDep,
    _: AuthDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> JSONResponse:
    """Семантический поиск похожих звонков (pgvector kNN, cosine)."""
    if not session.bind or not session.bind.url.get_backend_name().startswith("postgresql"):
        raise HTTPException(501, "поиск требует Postgres (pgvector)")
    from sqlalchemy import text as sqltext

    from polylog.models.calls import Call

    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "звонок не найден")
    row = (
        await session.execute(
            sqltext(
                "SELECT vector::text FROM embeddings "
                "WHERE entity_type='call' AND entity_id=:eid ORDER BY created_at DESC LIMIT 1"
            ),
            {"eid": str(call_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(409, "у звонка нет вектора — прогрейте embed (embed_backfill.py)")
    similar = (
        (
            await session.execute(
                sqltext(
                    """
                    SELECT e.entity_id, 1 - (e.vector <=> CAST(:qv AS halfvec)) AS sim,
                           c.phone_from, c.phone_to, c.direction, c.started_at, c.duration_sec
                    FROM embeddings e JOIN calls c ON c.id::text = e.entity_id
                    WHERE e.entity_type='call' AND e.org_id=:org AND e.entity_id <> :eid
                    ORDER BY e.vector <=> CAST(:qv AS halfvec)
                    LIMIT :lim
                    """
                ),
                {"qv": row[0], "org": call.org_id, "eid": str(call_id), "lim": limit},
            )
        )
        .mappings()
        .all()
    )
    return JSONResponse({
        "call_id": str(call_id),
        "items": [
            {
                "call_id": s["entity_id"],
                "similarity": round(float(s["sim"]), 4),
                "phone": (s["phone_to"] if s["direction"] == "outbound" else s["phone_from"])
                or s["phone_from"]
                or s["phone_to"],
                "started_at": s["started_at"].isoformat(),
                "duration_sec": s["duration_sec"],
            }
            for s in similar
        ],
    })
