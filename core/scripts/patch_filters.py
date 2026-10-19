from pathlib import Path

p = Path(r"F:\Z\rechevaua analitika\core\polylog\api\main.py")
t = p.read_text(encoding="utf-8")

# 1. list_calls: фильтры период + длительность
old = '''    @app.get("/api/v1/calls", response_model=CallList)
    async def list_calls(
        session: SessionDep,
        _: AuthDep,
        state: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CallList:
        org = await get_default_org(session)
        conds = [Call.org_id == org.id]
        if state:
            conds.append(Call.state == state)'''
new = '''    @app.get("/api/v1/calls", response_model=CallList)
    async def list_calls(
        session: SessionDep,
        _: AuthDep,
        state: Annotated[str | None, Query()] = None,
        days: Annotated[int | None, Query(ge=1, le=365)] = None,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CallList:
        org = await get_default_org(session)
        conds = [Call.org_id == org.id]
        if state:
            conds.append(Call.state == state)
        if days:
            conds.append(Call.started_at >= datetime.now(UTC) - timedelta(days=days))
        if duration_min is not None:
            conds.append(Call.duration_sec >= duration_min)
        if duration_max is not None:
            conds.append(Call.duration_sec <= duration_max)'''
assert old in t, "list_calls anchor"
t = t.replace(old, new, 1)

# timedelta import
t = t.replace(
    "from datetime import UTC, datetime\n",
    "from datetime import UTC, datetime, timedelta\n",
    1,
)

# 2. stats_summary: фильтр длительности + общие conds
old = '''        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)

        total = (
            await session.execute(
                select(func.count()).select_from(Call)
                .where(Call.org_id == org.id, Call.started_at >= since)
            )
        ).scalar_one()
        done = (
            await session.execute(
                select(func.count()).select_from(Call)
                .where(Call.org_id == org.id, Call.started_at >= since,
                       Call.state == CallState.done.value)
            )
        ).scalar_one()
        avg_score = (
            await session.execute(
                select(func.avg(Score.total)).join(Call, Call.id == Score.call_id)
                .where(Call.org_id == org.id, Call.started_at >= since)
            )
        ).scalar_one()
        top_objections = (
            (
                await session.execute(
                    select(Objection.type, func.count().label("cnt"))
                    .join(Call, Call.id == Objection.call_id)
                    .where(Call.org_id == org.id, Call.started_at >= since)
                    .group_by(Objection.type)
                    .order_by(func.count().desc())
                    .limit(5)
                )
            ).all()
        )'''
new = '''        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)
        conds = [Call.org_id == org.id, Call.started_at >= since]
        if duration_min is not None:
            conds.append(Call.duration_sec >= duration_min)
        if duration_max is not None:
            conds.append(Call.duration_sec <= duration_max)

        total = (
            await session.execute(
                select(func.count()).select_from(Call).where(*conds)
            )
        ).scalar_one()
        done = (
            await session.execute(
                select(func.count()).select_from(Call)
                .where(*conds, Call.state == CallState.done.value)
            )
        ).scalar_one()
        avg_score = (
            await session.execute(
                select(func.avg(Score.total)).join(Call, Call.id == Score.call_id)
                .where(*conds)
            )
        ).scalar_one()
        top_objections = (
            (
                await session.execute(
                    select(Objection.type, func.count().label("cnt"))
                    .join(Call, Call.id == Objection.call_id)
                    .where(*conds)
                    .group_by(Objection.type)
                    .order_by(func.count().desc())
                    .limit(5)
                )
            ).all()
        )'''
assert old in t, "stats anchor"
t = t.replace(old, new, 1)

# параметры stats
old = '''    async def stats_summary(
        session: SessionDep,
        _: AuthDep,
        days: Annotated[int, Query(ge=1, le=365)] = 30,
    ) -> JSONResponse:'''
new = '''    async def stats_summary(
        session: SessionDep,
        _: AuthDep,
        days: Annotated[int, Query(ge=1, le=365)] = 30,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
    ) -> JSONResponse:'''
assert old in t, "stats params anchor"
t = t.replace(old, new, 1)

# 3. risks/top: factors + recent_call_ids для дрилдауна
old = '''        items = []
        for cid in contact_ids:
            r = await risk_for_contact(session, org.id, cid)
            if r is not None:
                items.append({
                    "contact_id": str(cid),
                    "score": r["score"],
                    "band": r["band"],
                    "top_factor": r["factors"][0]["description"] if r["factors"] else "",
                    "calls_total": r.get("features", {}).get("calls_total"),
                })
        items.sort(key=lambda x: -x["score"])
        return JSONResponse({"items": items[:limit], "total": len(items)})'''
new = '''        items = []
        for cid in contact_ids:
            r = await risk_for_contact(session, org.id, cid)
            if r is not None:
                recent = (
                    (
                        await session.execute(
                            select(Call.id)
                            .where(Call.org_id == org.id, Call.contact_id == cid)
                            .order_by(Call.started_at.desc())
                            .limit(5)
                        )
                    )
                    .scalars()
                    .all()
                )
                items.append({
                    "contact_id": str(cid),
                    "score": r["score"],
                    "band": r["band"],
                    "top_factor": r["factors"][0]["description"] if r["factors"] else "",
                    "factors": r["factors"][:3],
                    "calls_total": r.get("features", {}).get("calls_total"),
                    "recent_call_ids": [str(c) for c in recent],
                })
        items.sort(key=lambda x: -x["score"])
        return JSONResponse({"items": items[:limit], "total": len(items)})'''
assert old in t, "risks anchor"
t = t.replace(old, new, 1)

# 4. clusters: call_ids членов кластера
old = '''        rows = (
            (
                await session.execute(
                    select(Objection.span_text, Objection.type)
                    .join(Call, Call.id == Objection.call_id)
                    .where(Call.org_id == org.id, Call.started_at >= since)
                    .limit(2000)
                )
            )
            .all()
        )'''
new = '''        rows = (
            (
                await session.execute(
                    select(Objection.span_text, Objection.type, Objection.call_id)
                    .join(Call, Call.id == Objection.call_id)
                    .where(Call.org_id == org.id, Call.started_at >= since)
                    .limit(2000)
                )
            )
            .all()
        )'''
assert old in t, "clusters rows anchor"
t = t.replace(old, new, 1)

old = '''        backend = EmbeddingBackend()
        vectors = backend.embed([t for t, _ in rows])
        items = [
            {"vector": v, "text": t, "type": ty}
            for v, (t, ty) in zip(vectors, rows, strict=True)
        ]
        clusters = cluster_items(items, threshold=threshold)
        return JSONResponse({
            "period_days": days,
            "threshold": threshold,
            "total_objections": len(rows),
            "clusters": [c.as_dict() for c in clusters[:20]],
        })'''
new = '''        backend = EmbeddingBackend()
        vectors = backend.embed([r[0] for r in rows])
        items = [
            {"vector": v, "text": txt, "type": ty, "call_id": str(cid)}
            for v, (txt, ty, cid) in zip(vectors, rows, strict=True)
        ]
        clusters = cluster_items(items, threshold=threshold)
        out = []
        for c in clusters[:20]:
            d = c.as_dict()
            member_calls = list(dict.fromkeys(items[i]["call_id"] for i in c.members))
            d["calls"] = [{"call_id": cid} for cid in member_calls[:8]]
            out.append(d)
        return JSONResponse({
            "period_days": days,
            "threshold": threshold,
            "total_objections": len(rows),
            "clusters": out,
        })'''
assert old in t, "clusters build anchor"
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("backend filters + drilldown applied")
