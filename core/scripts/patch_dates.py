from pathlib import Path

p = Path(r"F:\Z\rechevaua analitika\core\polylog\api\main.py")
t = p.read_text(encoding="utf-8")

# --- 1. list_calls: date_from/date_to ---
old = '''        state: Annotated[str | None, Query()] = None,
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
            conds.append(Call.started_at >= datetime.now(UTC) - timedelta(days=days))'''
new = '''        state: Annotated[str | None, Query()] = None,
        days: Annotated[int | None, Query(ge=1, le=365)] = None,
        date_from: Annotated[str | None, Query()] = None,
        date_to: Annotated[str | None, Query()] = None,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CallList:
        org = await get_default_org(session)
        conds = [Call.org_id == org.id]
        if state:
            conds.append(Call.state == state)
        if date_from:
            conds.append(Call.started_at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
        if date_to:
            conds.append(Call.started_at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))
        if not date_from and not date_to and days:
            conds.append(Call.started_at >= datetime.now(UTC) - timedelta(days=days))'''
assert old in t, "list_calls anchor"
t = t.replace(old, new, 1)

# --- 2. stats_summary: параметры + conds ---
old = '''        days: Annotated[int, Query(ge=1, le=365)] = 30,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
    ) -> JSONResponse:
        """Сводка для дашборда РОПа (doc 08 §4.1): объёмы, скоры, топ-возражения."""
        from datetime import timedelta

        from sqlalchemy import func

        from polylog.models.calls import Call, Objection, Score
        from polylog.models.enums import CallState

        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)
        conds = [Call.org_id == org.id, Call.started_at >= since]'''
new = '''        days: Annotated[int, Query(ge=1, le=365)] = 30,
        date_from: Annotated[str | None, Query()] = None,
        date_to: Annotated[str | None, Query()] = None,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
    ) -> JSONResponse:
        """Сводка для дашборда РОПа (doc 08 §4.1): объёмы, оценки, топ-возражения."""
        from datetime import timedelta

        from sqlalchemy import func

        from polylog.models.calls import Call, Objection, Score
        from polylog.models.enums import CallState

        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)
        conds = [Call.org_id == org.id, Call.started_at >= since]
        if date_from:
            conds.append(Call.started_at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
        if date_to:
            conds.append(Call.started_at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))'''
assert old in t, "stats anchor"
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("both applied")
