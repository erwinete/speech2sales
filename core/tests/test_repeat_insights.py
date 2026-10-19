"""Повторяющиеся нерешённые проблемы (Root-Cause «Unresolved Repeat»):
чистый хелпер find_repeats, блок repeat в карточке, метки риска в реестре,
инсайты repeat_objection в refresh_insights (дедап-upsert)."""

import uuid
from datetime import UTC, datetime, timedelta

from conftest import AUTH, wav_bytes

from polylog.insights.repeat import find_repeats


def _mk(started: datetime, *objections: tuple[str, str | None]) -> tuple:
    return (started, list(objections))


async def _seed_objection(session, call_id: uuid.UUID, ty: str, status: str | None) -> None:
    from polylog.models.calls import Objection

    session.add(
        Objection(
            call_id=call_id,
            type=ty,
            span_text="тестовое возражение",
            confidence=0.9,
            model_id="rules@test",
            response_status=status,
        )
    )


def test_find_repeats_pure():
    now = datetime.now(UTC)
    d1, d2, d3 = now - timedelta(days=9), now - timedelta(days=4), now - timedelta(days=1)

    # одна проблема в двух звонках, последняя отработка неуспешна → повтор
    reps = find_repeats([
        _mk(d1, ("price", "ignored")),
        _mk(d2, ("price", "handled_partial")),
    ])
    assert len(reps) == 1
    assert reps[0]["type"] == "price" and reps[0]["calls"] == 2
    assert reps[0]["last_status"] == "handled_partial"

    # последняя отработка успешна — повтора нет
    assert find_repeats([
        _mk(d1, ("price", "ignored")),
        _mk(d2, ("price", "handled_success")),
    ]) == []

    # тип прозвучал один раз — не повтор
    assert find_repeats([_mk(d1, ("price", "ignored"))]) == []

    # несколько типов — сортировка по числу звонков; порядок звонков не важен
    reps = find_repeats([
        _mk(d3, ("timing", "ignored")),
        _mk(d1, ("price", "ignored")),
        _mk(d2, ("price", "handled_partial"), ("timing", "ignored")),
    ])
    assert [r["type"] for r in reps] == ["price", "timing"]
    assert reps[0]["last_at"] == d2.isoformat()


async def test_contact_card_repeat_block(app_client):
    """Одно возражение в двух звонках контакта → блок repeat в карточке."""
    client, app = app_client
    ids = []
    for i, size in enumerate((2.0, 3.0)):
        r = await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"r{i}.wav", wav_bytes(size), "audio/wav")},
            data={"direction": "outbound", "phone_to": "+79009880000"},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["call"])

    async with app.state.sessionmaker() as s:
        await _seed_objection(s, uuid.UUID(ids[0]["id"]), "price", "ignored")
        await _seed_objection(s, uuid.UUID(ids[1]["id"]), "price", "handled_partial")
        await s.commit()

    r = await client.get(f"/api/v1/contacts/{ids[0]['contact_id']}/card", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["repeat"]["items"]
    assert len(items) == 1
    assert items[0]["type"] == "price"
    assert items[0]["calls"] == 2
    assert items[0]["last_status"] == "handled_partial"


async def test_contact_card_no_repeat_when_resolved(app_client):
    client, app = app_client
    ids = []
    for i, size in enumerate((2.0, 3.0)):
        r = await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"s{i}.wav", wav_bytes(size), "audio/wav")},
            data={"direction": "outbound", "phone_to": "+79009881111"},
        )
        ids.append(r.json()["call"])

    async with app.state.sessionmaker() as s:
        await _seed_objection(s, uuid.UUID(ids[0]["id"]), "price", "ignored")
        await _seed_objection(s, uuid.UUID(ids[1]["id"]), "price", "handled_success")
        await s.commit()

    r = await client.get(f"/api/v1/contacts/{ids[0]['contact_id']}/card", headers=AUTH)
    assert r.json()["repeat"]["items"] == []


async def test_registry_risk_and_score(app_client):
    """Реестр (без q): риск-метки и средний скор; неотработанное возражение
    поднимает риск так же, как это делает /contacts/{id}/risk."""
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("a.wav", wav_bytes(3.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79007770001"},
    )
    call = r.json()["call"]

    # без возражений: риск только из «нет скоров» — низкий
    r = await client.get("/api/v1/contacts/search", headers=AUTH)
    row = next(i for i in r.json()["items"] if i["phones"] == ["+79007770001"])
    assert row["risk_score"] is not None and 0 <= row["risk_score"] <= 100
    assert row["risk_band"] in ("low", "medium", "high")
    assert row["avg_score"] is not None
    assert row["objections_unhandled"] == 0
    base_risk = row["risk_score"]

    # неотработанное возражение → вклад в риск появился
    async with app.state.sessionmaker() as s:
        await _seed_objection(s, uuid.UUID(call["id"]), "price", "ignored")
        await s.commit()

    r = await client.get("/api/v1/contacts/search", headers=AUTH)
    row = next(i for i in r.json()["items"] if i["phones"] == ["+79007770001"])
    assert row["objections_unhandled"] == 1
    assert row["risk_score"] > base_risk

    # согласованность с точечным расчётом risk_for_contact
    r = await client.get(f"/api/v1/contacts/{call['contact_id']}/risk", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["score"] == row["risk_score"]


async def test_insights_severity_filter(app_client):
    """GET /insights?severity=… фильтрует ленту по важности."""
    client, app = app_client
    from sqlalchemy import text

    from polylog.models.system import Insight

    async with app.state.sessionmaker() as s:
        org_id = uuid.UUID((await s.execute(text("SELECT id FROM orgs LIMIT 1"))).scalar_one())
        s.add(Insight(
            org_id=org_id, kind="risk_account", severity="critical",
            payload={"score": 80, "band": "high", "contact_id": str(uuid.uuid4())},
            generated_by="test", status="new",
        ))
        s.add(Insight(
            org_id=org_id, kind="repeat_objection", severity="warning",
            payload={"contact_id": str(uuid.uuid4()), "type": "price", "calls": 2},
            generated_by="test", status="new",
        ))
        await s.commit()

    r = await client.get("/api/v1/insights", headers=AUTH)
    kinds = {i["kind"] for i in r.json()["items"]}
    assert {"risk_account", "repeat_objection"} <= kinds

    r = await client.get("/api/v1/insights", headers=AUTH, params={"severity": "critical"})
    items = r.json()["items"]
    assert items and all(i["severity"] == "critical" for i in items)

    r = await client.get("/api/v1/insights", headers=AUTH, params={"severity": "warning"})
    items = r.json()["items"]
    assert items and all(i["severity"] == "warning" for i in items)


async def test_refresh_insights_repeat_and_dedup(app_client):
    """refresh_insights: repeat_objection создаётся и не дублируется повторным запуском."""
    from sqlalchemy import select

    from polylog.models.system import Insight
    from polylog.periodic import refresh_insights

    client, app = app_client
    ids = []
    for i, size in enumerate((2.0, 3.0)):
        r = await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"p{i}.wav", wav_bytes(size), "audio/wav")},
            data={"direction": "outbound", "phone_to": "+79009882222"},
        )
        ids.append(r.json()["call"])

    async with app.state.sessionmaker() as s:
        await _seed_objection(s, uuid.UUID(ids[0]["id"]), "price", "ignored")
        await _seed_objection(s, uuid.UUID(ids[1]["id"]), "price", "ignored")
        await s.commit()

        counts = await refresh_insights(s)
        assert counts["repeat_objection"] >= 1

        rows = (
            (await s.execute(select(Insight).where(Insight.kind == "repeat_objection")))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].payload["type"] == "price"
        assert rows[0].payload["contact_id"] == ids[0]["contact_id"]
        assert rows[0].severity == "warning"

        # повторный запуск — дедап: upsert, а не новый инсайт
        await refresh_insights(s)
        rows2 = (
            (await s.execute(select(Insight).where(Insight.kind == "repeat_objection")))
            .scalars()
            .all()
        )
        assert len(rows2) == 1


async def test_nightly_s6_gated_by_env(app_client, monkeypatch):
    """run_nightly_s6 bez POLYLOG_NIGHTLY_S6=1 — no-op."""
    from polylog.periodic import run_nightly_s6

    monkeypatch.delenv("POLYLOG_NIGHTLY_S6", raising=False)
    assert await run_nightly_s6() == {"status": "skipped"}


async def test_nightly_s6_missing_inputs(app_client, monkeypatch, tmp_path):
    """S env, no tools/datasets u kornya — missing_inputs, bez isklucheniya."""
    from polylog import periodic as periodic_mod

    monkeypatch.setenv("POLYLOG_NIGHTLY_S6", "1")
    monkeypatch.setattr(periodic_mod, "_repo_root", lambda: tmp_path)
    assert await periodic_mod.run_nightly_s6() == {"status": "missing_inputs"}
