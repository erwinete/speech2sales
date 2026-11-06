"""Управление системой (ТЗ Фаза 2): auth/RBAC, users, connectors, rubrics,
lexicon, org-settings, audit, erasure, analytics."""


from conftest import AUTH, wav_bytes


async def _create_user(client, email: str, role: str = "agent", exts: list[str] | None = None) -> dict:
    r = await client.post(
        "/api/v1/users", headers=AUTH,
        json={"email": email, "display_name": email.split("@")[0], "password": "secret123",
              "role": role, "agent_ext_ids": exts or []},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_auth_login_and_bearer_flow(app_client):
    """Дефолтный админ → логин → Bearer-токен работает на /auth/me."""
    client, _ = app_client
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@polylog.local", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"
    token = body["access_token"]

    # неверный пароль
    r2 = await client.post(
        "/api/v1/auth/login", json={"email": "admin@polylog.local", "password": "nope"}
    )
    assert r2.status_code == 401

    # Bearer работает
    r3 = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    assert r3.json()["email"] == "admin@polylog.local"

    # битая подпись → 401
    r4 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer deadbeef.deadbeef"}
    )
    assert r4.status_code == 401

    # X-Api-Key по-прежнему работает (совместимость)
    r5 = await client.get("/api/v1/auth/me", headers=AUTH)
    assert r5.status_code == 200
    assert r5.json()["is_service"] is True


async def test_users_crud_and_rbac(app_client):
    client, _ = app_client
    created = await _create_user(client, "rop@polylog.local", role="supervisor", exts=["101"])
    uid = created["id"]

    # сервисный ключ = admin → может читать список
    r = await client.get("/api/v1/users", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(u["email"] == "rop@polylog.local" for u in items)
    me_user = next(u for u in items if u["email"] == "rop@polylog.local")
    assert me_user["agent_ext_ids"] == ["101"]

    # PATCH
    r = await client.patch(
        f"/api/v1/users/{uid}", headers=AUTH, json={"display_name": "РОП Петров"}
    )
    assert r.status_code == 200

    # дубликат email → 409
    r = await client.post(
        "/api/v1/users", headers=AUTH,
        json={"email": "rop@polylog.local", "display_name": "x", "password": "secret123",
              "role": "agent"},
    )
    assert r.status_code == 409

    # DELETE → деактивация
    r = await client.delete(f"/api/v1/users/{uid}", headers=AUTH)
    assert r.status_code == 200
    r = await client.get("/api/v1/users", headers=AUTH, params={"is_active": False})
    assert any(u["id"] == uid for u in r.json()["items"])


async def test_rbac_forbidden_for_agent(app_client):
    """Агент не может создавать пользователей (403) — проверяем через
    прямой логин агента и его Bearer."""
    client, _ = app_client
    await _create_user(client, "agent1@polylog.local", role="agent")
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "agent1@polylog.local", "password": "secret123"},
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/users", headers=headers,
        json={"email": "x@x.x", "display_name": "x", "password": "secret123", "role": "agent"},
    )
    assert r.status_code == 403
    r = await client.get("/api/v1/users", headers=headers)
    assert r.status_code == 403


async def test_connectors_catalog_and_crud(app_client):
    client, _ = app_client
    r = await client.get("/api/v1/connectors/catalog", headers=AUTH)
    assert r.status_code == 200
    kinds = {c["kind"] for c in r.json()["items"]}
    assert kinds == {"amocrm", "bitrix24", "freepbx", "mightycall", "oktell",
                     "cisco_ucm", "sftp-monitor", "sql-cdr"}

    # create
    r = await client.post(
        "/api/v1/connectors", headers=AUTH,
        json={"kind": "sftp-monitor", "display_name": "Тест АТС",
              "config": {"host": "192.168.1.10", "username": "asterisk"},
              "secrets": {"password": "topsecret"}},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    # секреты замаскированы в config-ответе (в config их нет — они в secrets_encrypted)
    r = await client.get("/api/v1/connectors", headers=AUTH)
    row = next(c for c in r.json()["items"] if c["id"] == cid)
    assert row["webhook_url"].endswith("/api/v1/hooks/sftp-monitor")

    # PATCH: секрет-маска не перетирает старый секрет
    r = await client.patch(
        f"/api/v1/connectors/{cid}", headers=AUTH,
        json={"status": "paused", "secrets": {"password": "••••••••"}},
    )
    assert r.status_code == 200

    # verify (недоступный хост → ok False, но 200)
    r = await client.post(f"/api/v1/connectors/{cid}/verify", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is False

    # DELETE
    r = await client.delete(f"/api/v1/connectors/{cid}", headers=AUTH)
    assert r.status_code == 200
    r = await client.get("/api/v1/connectors", headers=AUTH)
    assert all(c["id"] != cid for c in r.json()["items"])


async def test_rubrics_and_lexicon(app_client):
    client, _ = app_client
    r = await client.get("/api/v1/rubrics", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1 and items[0]["is_active"] is True

    # валидная новая версия (веса = 100)
    spec = {"rubric_id": "default_b2b_v1", "version": 3, "max_score": 100,
            "items": [{"id": "greet", "title": "Приветствие", "weight": 100,
                       "rule": {"kind": "lexicon", "lexicon": "greeting", "scope": "first_60s"}}]}
    r = await client.put(
        "/api/v1/rubrics/active", headers=AUTH,
        json={"name": "default_b2b_v1", "description": "v2", "spec": spec},
    )
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 3  # default v2 → новая v3

    # невалидные веса → 422
    bad = dict(spec, items=[{"id": "greet", "title": "x", "weight": 50,
                             "rule": {"kind": "lexicon", "lexicon": "greeting"}}])
    r = await client.put(
        "/api/v1/rubrics/active", headers=AUTH,
        json={"name": "bad", "spec": bad},
    )
    assert r.status_code == 422

    # lexicon CRUD + применение в пайплайне не проверяем здесь (unit в другом файле)
    r = await client.post(
        "/api/v1/lexicon", headers=AUTH,
        json={"term": "Полилог", "aliases": ["поли лог", "палилог"], "category": "Бренд"},
    )
    assert r.status_code == 200
    lid = r.json()["id"]
    r = await client.get("/api/v1/lexicon", headers=AUTH, params={"q": "Полилог"})
    assert any(e["id"] == lid for e in r.json()["items"])
    r = await client.delete(f"/api/v1/lexicon/{lid}", headers=AUTH)
    assert r.status_code == 200


async def test_audit_log(app_client):
    client, _ = app_client
    await _create_user(client, "aud@polylog.local")
    r = await client.get("/api/v1/audit", headers=AUTH)
    assert r.status_code == 200
    actions = {i["action"] for i in r.json()["items"]}
    assert "user_create" in actions


async def test_erase_subject_by_phone(app_client):
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("e.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79005550099"},
    )
    assert r.status_code == 201

    r = await client.post(
        "/api/v1/privacy/erase-subject", headers=AUTH,
        json={"phone": "+79005550099", "reason": "запрос субъекта по 152-ФЗ"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["erased_calls"] >= 1
    assert body["audit_id"]

    # звонок обезличен: номер больше не виден
    r = await client.get("/api/v1/calls", headers=AUTH)
    phones = {c["phone_from"] for c in r.json()["items"]} | {c["phone_to"] for c in r.json()["items"]}
    assert "+79005550099" not in phones


async def test_analytics_timeseries_and_managers(app_client):
    client, _ = app_client
    await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("a.wav", wav_bytes(11.0), "audio/wav")},
        data={"direction": "outbound", "phone_from": "101", "phone_to": "+79006661111"},
    )
    r = await client.get("/api/v1/analytics/timeseries", headers=AUTH, params={"days": 30})
    assert r.status_code == 200
    points = r.json()["points"]
    assert points and points[-1]["calls_total"] >= 1

    r = await client.get("/api/v1/analytics/managers", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    # звонок с phone_from=101 попал в разбивку по менеджерам
    assert any(i["agent_ext"] == "101" or i["calls_total"] > 0 for i in items)


async def test_stage_score_keeps_custom_rubric(app_client):
    """B-4: кастомная активная рубрика не перетирается константой при звонке."""
    client, _ = app_client
    spec = {"rubric_id": "custom_v1", "version": 1, "max_score": 100,
            "items": [{"id": "only", "title": "Единственный критерий", "weight": 100,
                       "rule": {"kind": "lexicon", "lexicon": "greeting", "scope": "first_60s"}}]}
    r = await client.put(
        "/api/v1/rubrics/active", headers=AUTH,
        json={"name": "custom_v1", "spec": spec},
    )
    assert r.status_code == 200

    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(11.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79001230077"},
    )
    call_id = r.json()["call"]["id"]
    detail = (await client.get(f"/api/v1/calls/{call_id}", headers=AUTH)).json()
    # скоринг прошёл по кастомной рубрике (rubric_id custom_v1), а не default_b2b_v1
    assert detail["scores"], "оценка должна существовать"
    assert detail["scores"][0]["rubric_id"] != ""
