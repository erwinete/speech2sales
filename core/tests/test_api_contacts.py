"""Customer 360 (M3): поиск клиентов и карточка контакта."""

import uuid

from conftest import AUTH, wav_bytes


async def _upload(client, fname: str, phone: str, size: float = 2.0) -> dict:
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": (fname, wav_bytes(size), "audio/wav")},
        data={"direction": "outbound", "phone_to": phone},
    )
    assert r.status_code == 201, r.text
    return r.json()["call"]


async def test_contacts_search_by_phone(app_client):
    client, _ = app_client
    call = await _upload(client, "a.wav", "+79001112233")
    r = await client.get("/api/v1/contacts/search", headers=AUTH, params={"q": "900111"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["contact_id"] == call["contact_id"]
    assert items[0]["phones"] == ["+79001112233"]
    assert items[0]["calls_total"] == 1
    assert items[0]["last_call_at"]


async def test_contacts_search_by_name(app_client):
    """Контакт без звонков (появится из CRM) находится по имени."""
    client, app = app_client
    from sqlalchemy import text

    from polylog.models.graph import Contact

    async with app.state.sessionmaker() as s:
        org_id = uuid.UUID((await s.execute(text("SELECT id FROM orgs LIMIT 1"))).scalar_one())
        s.add(Contact(org_id=org_id, display_name="Иван Петров"))
        await s.commit()

    r = await client.get("/api/v1/contacts/search", headers=AUTH, params={"q": "Иван"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["display_name"] == "Иван Петров"
    assert items[0]["calls_total"] == 0
    assert items[0]["phones"] == []


async def test_contacts_search_requires_query(app_client):
    """Слишком короткий q → 422 (пустой q валиден — это реестр всех клиентов)."""
    client, _ = app_client
    r = await client.get("/api/v1/contacts/search", headers=AUTH, params={"q": "9"})
    assert r.status_code == 422


async def test_contacts_list_all(app_client):
    """Без q — общий реестр: все контакты org, активные сверху."""
    client, _ = app_client
    await _upload(client, "a.wav", "+79001110001", size=2.0)
    await _upload(client, "b.wav", "+79001110002", size=2.5)
    # ещё один звонок первого номера — он должен оказаться выше по свежей активности
    await _upload(client, "c.wav", "+79001110001", size=3.0)

    r = await client.get("/api/v1/contacts/search", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    phones = [p for it in items for p in it["phones"]]
    assert "+79001110001" in phones and "+79001110002" in phones
    with_calls = [it for it in items if it["calls_total"] > 0]
    assert len(with_calls) == 2
    # сортировка по последней активности: +79001110001 (2 звонка) выше
    assert with_calls[0]["phones"] == ["+79001110001"]
    assert all(it["last_call_at"] for it in with_calls)


async def test_contact_card_aggregates(app_client):
    """Два звонка одного номера → карточка: телефоны, статистика, скоры, риск."""
    client, _ = app_client
    c1 = await _upload(client, "a.wav", "+79005550011", size=2.0)
    await _upload(client, "b.wav", "+79005550011", size=3.0)

    r = await client.get(f"/api/v1/contacts/{c1['contact_id']}/card", headers=AUTH)
    assert r.status_code == 200
    body = r.json()

    assert body["phones"] == ["+79005550011"]
    assert body["company"] is None
    assert body["deals"] == []
    assert body["stats"]["calls_total"] == 2
    assert body["stats"]["done_calls"] == 2
    assert body["stats"]["avg_score"] is not None
    assert body["stats"]["first_call_at"] <= body["stats"]["last_call_at"]
    assert body["stats"]["talk_sec_total"] > 0

    assert len(body["calls"]) == 2
    # новые сверху; у обработанных звонков есть скор
    assert body["calls"][0]["started_at"] >= body["calls"][1]["started_at"]
    assert all(c["score_total"] is not None for c in body["calls"])
    assert body["calls"][0]["chain_depth"] is not None

    assert body["risk"] is not None
    assert 0 <= body["risk"]["score"] <= 100
    assert body["risk"]["factors"]

    # sqlite без pgvector — блок похожих отсутствует, взаимодействий нет
    assert body["similar"] is None
    assert body["interactions"] == []


async def test_contact_card_contact_without_calls(app_client):
    client, app = app_client
    from sqlalchemy import text

    from polylog.models.graph import Contact

    async with app.state.sessionmaker() as s:
        org_id = uuid.UUID((await s.execute(text("SELECT id FROM orgs LIMIT 1"))).scalar_one())
        s.add(Contact(org_id=org_id, display_name="Мария Смирнова"))
        await s.commit()
        contact_id = uuid.UUID(
            (await s.execute(text("SELECT id FROM contacts LIMIT 1"))).scalar_one()
        )

    r = await client.get(f"/api/v1/contacts/{contact_id}/card", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["calls_total"] == 0
    assert body["calls"] == []
    assert body["risk"] is None
    assert body["contact"]["display_name"] == "Мария Смирнова"


async def test_contact_card_unknown_404(app_client):
    client, _ = app_client
    r = await client.get(f"/api/v1/contacts/{uuid.uuid4()}/card", headers=AUTH)
    assert r.status_code == 404
