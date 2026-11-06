"""Роутер контактов и компаний: поиск/реестр, цепочки, карточка 360, риск."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from polylog.api.deps import AuthDep, SessionDep
from polylog.graph.service import get_default_org
from polylog.models.calls import Call
from polylog.models.graph import Company, Contact, Deal, EntityLink, PhoneNumber

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])


@router.get("/search")
async def contacts_search(
    session: SessionDep,
    _: AuthDep,
    q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JSONResponse:
    """Клиенты для Customer 360. Без q — общий реестр всех контактов org
    (сортировка по свежей активности); с q — цифры → подстрока E.164,
    буквы → ilike по display_name."""
    from polylog.risk.batch import compute_org_risks_batch

    org = await get_default_org(session)

    contact_ids: set[uuid.UUID] = set()
    if q is None or not q.strip():
        all_contacts = (
            (
                await session.execute(
                    select(Contact)
                    .where(Contact.org_id == org.id)
                    .order_by(Contact.created_at.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        contact_ids = {c.id for c in all_contacts}
    else:
        if len(q) < 2:
            raise HTTPException(422, "q должен быть не короче 2 символов")
        digits = re.sub(r"\D+", "", q)
        if digits:
            phones = (
                (
                    await session.execute(
                        select(PhoneNumber).where(
                            PhoneNumber.org_id == org.id,
                            PhoneNumber.e164.like(f"%{digits}%"),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if phones:
                links = (
                    (
                        await session.execute(
                            select(EntityLink).where(
                                EntityLink.org_id == org.id,
                                EntityLink.src_type == "contact",
                                EntityLink.dst_type == "phone_number",
                                EntityLink.rel == "has_phone",
                                EntityLink.dst_id.in_([str(p.id) for p in phones]),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                contact_ids.update(uuid.UUID(lnk.src_id) for lnk in links)
        if any(ch.isalpha() for ch in q):
            by_name = (
                (
                    await session.execute(
                        select(Contact).where(
                            Contact.org_id == org.id,
                            Contact.display_name.ilike(f"%{q}%"),
                        )
                    )
                )
                .scalars()
                .all()
            )
            contact_ids.update(c.id for c in by_name)

    if not contact_ids:
        return JSONResponse({"items": []})

    links = (
        (
            await session.execute(
                select(EntityLink).where(
                    EntityLink.org_id == org.id,
                    EntityLink.src_type == "contact",
                    EntityLink.dst_type == "phone_number",
                    EntityLink.rel == "has_phone",
                    EntityLink.src_id.in_([str(c) for c in contact_ids]),
                )
            )
        )
        .scalars()
        .all()
    )
    phones_by_contact: dict[str, list[str]] = {}
    if links:
        phone_rows = (
            (
                await session.execute(
                    select(PhoneNumber).where(
                        PhoneNumber.id.in_([uuid.UUID(lnk.dst_id) for lnk in links])
                    )
                )
            )
            .scalars()
            .all()
        )
        e164_by_id = {str(p.id): p.e164 for p in phone_rows}
        for lnk in links:
            e164 = e164_by_id.get(lnk.dst_id)
            if e164:
                phones_by_contact.setdefault(lnk.src_id, []).append(e164)

    contacts = (
        (await session.execute(select(Contact).where(Contact.id.in_(contact_ids))))
        .scalars()
        .all()
    )

    # пакетный риск: 3 агрегата на всю выборку (B-3)
    risks = await compute_org_risks_batch(session, org.id, list(contact_ids))

    items = []
    for c in contacts:
        risk = risks.get(c.id)
        feats = (risk or {}).get("features", {})
        items.append({
            "contact_id": str(c.id),
            "display_name": c.display_name,
            "phones": sorted(phones_by_contact.get(str(c.id), [])),
            "calls_total": feats.get("calls_total", 0),
            "last_call_at": feats.get("last_call_at"),
            "risk_score": risk["score"] if risk else None,
            "risk_band": risk["band"] if risk else None,
            "avg_score": feats.get("avg_score"),
            "objections_unhandled": feats.get("objections_unhandled", 0),
            "sentiment_last": feats.get("sentiment_last"),
            "sentiment_trend": feats.get("sentiment_trend"),
        })
    items.sort(key=lambda x: x["last_call_at"] or "", reverse=True)
    items.sort(key=lambda x: x["last_call_at"] is None)  # стабильно: активные выше
    return JSONResponse({"items": items[:limit]})


@router.get("/{contact_id}/calls")
async def contact_calls(contact_id: uuid.UUID, session: SessionDep, _: AuthDep) -> JSONResponse:
    """Цепочка звонков контакта (thread_id/previous_call_id, doc 03 §4.1)."""
    rows = (
        (
            await session.execute(
                select(Call)
                .where(Call.contact_id == contact_id)
                .order_by(Call.started_at, Call.id)
            )
        )
        .scalars()
        .all()
    )
    from polylog.api.routers.calls import _call_to_out

    return JSONResponse({
        "total": len(rows),
        "items": [_call_to_out(c).model_dump(mode="json") for c in rows],
    })


@router.get("/{contact_id}/card")
async def contact_card(contact_id: uuid.UUID, session: SessionDep, _: AuthDep) -> JSONResponse:
    """Карточка Customer 360: профиль + таймлайн + риск + повторы + NBA + похожие."""
    from sqlalchemy import or_
    from sqlalchemy import text as sqltext

    from polylog.insights.nba import next_best_actions
    from polylog.insights.repeat import find_repeats
    from polylog.models.calls import CallMetrics, Objection, Score, Signal
    from polylog.risk.batch import compute_org_risks_batch

    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(404, "контакт не найден")

    links = (
        (
            await session.execute(
                select(EntityLink).where(
                    EntityLink.src_type == "contact",
                    EntityLink.dst_type == "phone_number",
                    EntityLink.rel == "has_phone",
                    EntityLink.src_id == str(contact.id),
                )
            )
        )
        .scalars()
        .all()
    )
    phones: list[str] = []
    if links:
        phone_rows = (
            (
                await session.execute(
                    select(PhoneNumber).where(
                        PhoneNumber.id.in_([uuid.UUID(lnk.dst_id) for lnk in links])
                    )
                )
            )
            .scalars()
            .all()
        )
        phones = sorted(p.e164 for p in phone_rows)

    company = None
    if contact.company_id is not None:
        comp = await session.get(Company, contact.company_id)
        if comp is not None:
            company = {"id": str(comp.id), "name": comp.name, "industry": comp.industry}

    deal_conds = [Deal.contact_id == contact.id]
    if contact.company_id is not None:
        deal_conds.append(Deal.company_id == contact.company_id)
    deals_rows = (
        (
            await session.execute(
                select(Deal).where(or_(*deal_conds)).order_by(Deal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    calls = (
        (
            await session.execute(
                select(Call)
                .where(Call.contact_id == contact.id)
                .order_by(Call.started_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    call_ids = [c.id for c in calls]
    score_by_call: dict[uuid.UUID, Score] = {}
    objections_by_call: dict[uuid.UUID, list[Objection]] = {}
    if call_ids:
        for sc in (
            await session.execute(
                select(Score).where(Score.call_id.in_(call_ids)).order_by(Score.created_at)
            )
        ).scalars().all():
            score_by_call[sc.call_id] = sc
        for o in (
            await session.execute(select(Objection).where(Objection.call_id.in_(call_ids)))
        ).scalars().all():
            objections_by_call.setdefault(o.call_id, []).append(o)

    interactions = (
        (
            await session.execute(
                select(Interaction_)
                .where(Interaction_.contact_id == contact.id, Interaction_.kind != "call")
                .order_by(Interaction_.occurred_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
        if (Interaction_ := _interactions_model())
        else []
    )

    risks = await compute_org_risks_batch(session, contact.org_id, [contact.id])
    risk = risks.get(contact.id)

    # похожие звонки: вектор последнего обработанного звонка с embedding
    similar = None
    if session.bind and session.bind.url.get_backend_name().startswith("postgresql"):
        for c in calls[:5]:
            vec = (
                await session.execute(
                    sqltext(
                        "SELECT vector::text FROM embeddings "
                        "WHERE entity_type='call' AND entity_id=:eid ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"eid": str(c.id)},
                )
            ).first()
            if vec is None:
                continue
            found = (
                (
                    await session.execute(
                        sqltext(
                            """
                            SELECT e.entity_id, 1 - (e.vector <=> CAST(:qv AS halfvec)) AS sim,
                                   c.phone_from, c.phone_to, c.direction, c.started_at, c.duration_sec
                            FROM embeddings e JOIN calls c ON c.id::text = e.entity_id
                            WHERE e.entity_type='call' AND e.org_id=:org AND e.entity_id <> :eid
                            ORDER BY e.vector <=> CAST(:qv AS halfvec)
                            LIMIT 5
                            """
                        ),
                        {"qv": vec[0], "org": contact.org_id, "eid": str(c.id)},
                    )
                )
                .mappings()
                .all()
            )
            similar = {
                "base_call_id": str(c.id),
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
                    for s in found
                ],
            }
            break

    # сентимент по звонкам + сигналы последнего звонка
    sentiment_by_call: dict[uuid.UUID, dict] = {}
    if call_ids:
        for m in (
            await session.execute(select(CallMetrics).where(CallMetrics.call_id.in_(call_ids)))
        ).scalars().all():
            cs = (m.metrics or {}).get("client_sentiment")
            if cs is not None:
                sentiment_by_call[m.call_id] = cs
    last_call_signals: list[str] = []
    if calls:
        last_call_signals = (
            (
                await session.execute(select(Signal.kind).where(Signal.call_id == calls[0].id))
            )
            .scalars()
            .all()
        )

    repeat_items = find_repeats(
        [
            (c.started_at, [(o.type, o.response_status) for o in objections_by_call.get(c.id, [])])
            for c in calls
        ]
    )

    all_objections = [o for lst in objections_by_call.values() for o in lst]
    score_vals = [sc.total for sc in score_by_call.values()]
    stats = {
        "calls_total": len(calls),
        "done_calls": sum(1 for c in calls if c.state == "done"),
        "first_call_at": calls[-1].started_at.isoformat() if calls else None,
        "last_call_at": calls[0].started_at.isoformat() if calls else None,
        "avg_score": round(sum(score_vals) / len(score_vals), 1) if score_vals else None,
        "objections_total": len(all_objections),
        "objections_unhandled": sum(
            1 for o in all_objections if o.response_status != "handled_success"
        ),
        "talk_sec_total": sum(c.duration_sec or 0 for c in calls),
        "sentiment_last": (
            sentiment_by_call[calls[0].id]["score"] if calls and calls[0].id in sentiment_by_call else None
        ),
        "sentiment_trend": (
            round(
                sentiment_by_call[calls[0].id]["score"] - sentiment_by_call[calls[-1].id]["score"], 3
            )
            if calls and calls[0].id in sentiment_by_call and calls[-1].id in sentiment_by_call and len(calls) > 1
            else None
        ),
    }

    last_call_for_nba = (
        {
            "score_total": score_by_call[calls[0].id].total if calls[0].id in score_by_call else None,
            "objections": [
                {"type": o.type, "response_status": o.response_status}
                for o in objections_by_call.get(calls[0].id, [])
            ],
            "signals": last_call_signals,
        }
        if calls
        else None
    )
    nba_items = next_best_actions(
        risk, repeat_items, stats, last_call_for_nba,
        sentiment_by_call.get(calls[0].id) if calls else None,
    )

    call_items = [
        {
            "id": str(c.id),
            "direction": c.direction,
            "phone_from": c.phone_from,
            "phone_to": c.phone_to,
            "started_at": c.started_at.isoformat(),
            "duration_sec": c.duration_sec,
            "state": c.state,
            "chain_depth": c.chain_depth,
            "score_total": score_by_call[c.id].total if c.id in score_by_call else None,
            "sentiment": sentiment_by_call[c.id]["score"] if c.id in sentiment_by_call else None,
            "objections": [
                {"type": o.type, "response_status": o.response_status, "start_ms": o.start_ms}
                for o in objections_by_call.get(c.id, [])
            ],
        }
        for c in calls
    ]

    return JSONResponse({
        "contact": {
            "id": str(contact.id),
            "display_name": contact.display_name,
            "created_at": contact.created_at.isoformat(),
        },
        "phones": phones,
        "company": company,
        "deals": [
            {
                "id": str(d.id),
                "stage": d.stage,
                "amount": float(d.amount) if d.amount is not None else None,
                "currency": d.currency,
                "status": d.status,
            }
            for d in deals_rows
        ],
        "stats": stats,
        "calls": call_items,
        "interactions": [
            {
                "id": str(i.id),
                "kind": i.kind,
                "occurred_at": i.occurred_at.isoformat(),
                "payload": i.payload,
            }
            for i in interactions
        ],
        "risk": risk,
        "repeat": {"items": repeat_items},
        "nba": {"items": nba_items},
        "similar": similar,
    })


def _interactions_model():
    from polylog.models.graph import Interaction

    return Interaction


@router.get("/{contact_id}/risk")
async def contact_risk(contact_id: uuid.UUID, session: SessionDep, _: AuthDep) -> JSONResponse:
    """Риск потери контакта (M5 scorecard + CatBoost при наличии модели)."""
    from polylog.risk import risk_for_contact

    org = await get_default_org(session)
    result = await risk_for_contact(session, org.id, contact_id)
    if result is None:
        raise HTTPException(404, "у контакта нет звонков")
    return JSONResponse(result)
