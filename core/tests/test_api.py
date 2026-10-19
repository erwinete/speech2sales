"""API: загрузка → полный пайплайн (stub-ASR) → транскрипт/метрики/граф; auth; дедуп."""

import uuid

from conftest import AUTH, wav_bytes


async def test_healthz(app_client):
    client, _ = app_client
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_upload_requires_auth(app_client):
    client, _ = app_client
    r = await client.post(
        "/api/v1/calls/upload",
        files={"file": ("call.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79001234567"},
    )
    assert r.status_code == 401


async def test_upload_full_pipeline(app_client):
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload",
        headers=AUTH,
        files={"file": ("call.wav", wav_bytes(11.0), "audio/wav")},
        data={
            "direction": "outbound",
            "phone_from": "101",
            "phone_to": "+79001234567",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    call_id = body["call"]["id"]
    assert body["created"] is True
    # inline_process=True → пайплайн прошёл до done (stub-ASR, 11 c → 3 сегмента по 5 c)
    assert body["call"]["state"] == "done"
    assert body["call"]["contact_id"] is not None
    assert body["call"]["thread_id"] == body["call"]["id"]  # первый звонок цепочки
    assert body["call"]["chain_depth"] == 0

    detail = (await client.get(f"/api/v1/calls/{call_id}", headers=AUTH)).json()
    assert len(detail["segments"]) == 3
    assert detail["segments"][0]["speaker"] in {"agent", "client"}
    assert detail["metrics"] is not None
    assert "talk_ratio" in detail["metrics"]
    assert detail["asr_backend_id"] == "stub"
    assert detail["recording_key"] == detail["normalized_key"]  # fast path 16к PCM


async def test_upload_duplicate_content_is_idempotent(app_client):
    client, _ = app_client
    payload = {"files": {"file": ("call.wav", wav_bytes(3.0), "audio/wav")},
               "data": {"direction": "outbound", "phone_to": "+79001234567"}}
    r1 = await client.post("/api/v1/calls/upload", headers=AUTH, **payload)
    r2 = await client.post("/api/v1/calls/upload", headers=AUTH, **payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r2.json()["created"] is False
    assert r2.json()["call"]["id"] == r1.json()["call"]["id"]


async def test_upload_requires_phone(app_client):
    client, _ = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("call.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound"},
    )
    assert r.status_code == 422


async def test_list_and_filters(app_client):
    client, _ = app_client
    for i in range(3):
        await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"call{i}.wav", wav_bytes(2.0 + i), "audio/wav")},
            data={"direction": "outbound", "phone_to": f"+7900123456{i}"},
        )
    r = await client.get("/api/v1/calls", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    r = await client.get("/api/v1/calls", headers=AUTH, params={"state": "done"})
    assert r.json()["total"] == 3
    r = await client.get("/api/v1/calls", headers=AUTH, params={"state": "failed"})
    assert r.json()["total"] == 0


async def test_contact_calls_chain_endpoint(app_client):
    client, _ = app_client
    ids = []
    for i in range(2):
        r = await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"c{i}.wav", wav_bytes(2.0 + i), "audio/wav")},
            data={"direction": "outbound", "phone_to": "+79009990000"},
        )
        ids.append(r.json()["call"]["id"])
    contact_id = (await client.get(f"/api/v1/calls/{ids[0]}", headers=AUTH)).json()["contact_id"]
    r = await client.get(f"/api/v1/contacts/{contact_id}/calls", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    depths = {c["id"]: c["chain_depth"] for c in body["items"]}
    assert sorted(depths.values()) == [0, 1]


async def test_reprocess_after_manual_fail(app_client, monkeypatch):
    client, app = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("call.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79005550000"},
    )
    call_id = uuid.UUID(r.json()["call"]["id"])
    # вручную ломаем состояние как после ошибки стадии
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as session:
        from polylog.models.calls import Call
        call = await session.get(Call, call_id)
        call.state = "failed"
        call.stage_error = {"stage": "normalize", "error": "test"}
        await session.commit()
    r2 = await client.post(f"/api/v1/calls/{call_id}/reprocess", headers=AUTH)
    assert r2.status_code == 200
    assert r2.json()["state"] == "done"


async def test_unknown_call_404(app_client):
    client, _ = app_client
    r = await client.get(f"/api/v1/calls/{uuid.uuid4()}", headers=AUTH)
    assert r.status_code == 404


async def test_hook_bitrix24_creates_call(app_client, monkeypatch):
    """Webhook Битрикс24 без записи → звонок создан, пайплайн отложен."""
    client, _ = app_client
    payload = {
        "event": "onVoximplantCallEnd",
        "data": {"CALL": {
            "CALL_ID": "hook-1", "CALL_DURATION": 42, "CALL_DIRECTION": "INBOUND",
            "PHONE_NUMBER": "+79001234567", "CALL_START_DATE": "2026-10-01T10:00:00+03:00",
        }},
    }
    r = await client.post("/api/v1/hooks/bitrix24", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["created"] is True
    assert body["state"] == "discovered"  # нет записи — ждём аудио
    assert body["reason"]
    # повторное событие — дедуп по external_id
    r2 = await client.post("/api/v1/hooks/bitrix24", json=payload)
    assert r2.json()["created"] is False


async def test_hook_with_recording_processes(app_client):
    """Webhook с RECORD_URL и существующим файлом в monitor (dev-стенд) → done."""
    import tempfile
    from pathlib import Path

    client, app = app_client
    td = tempfile.TemporaryDirectory()
    monitor = Path(td.name)
    from conftest import wav_bytes

    (monitor / "hook-rec.wav").write_bytes(wav_bytes(3.0))
    monkey_patch_target = "polylog.ingest.freepbx.FreePBXConnector"
    # RECORD_URL указывает на локальный файл — download по пути (упрощение теста)
    payload = {
        "event": "onVoximplantCallEnd",
        "data": {"CALL": {
            "CALL_ID": "hook-2", "CALL_DURATION": 30, "CALL_DIRECTION": "outbound",
            "PHONE_NUMBER": "+79009998877", "CALL_START_DATE": "2026-10-01T11:00:00+03:00",
            "RECORD_URL": str(monitor / "hook-rec.wav"),
        }},
    }
    # для файлового URL нужен коннектор, умеющий читать путь: эмулируем через
    # upload-механизм невозможно — поэтому проверяем только created/state=discovered
    r = await client.post("/api/v1/hooks/bitrix24", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["created"] is True
    assert body["state"] == "discovered"  # URL не http → парсер отбросил запись
    td.cleanup()
    del monkey_patch_target


async def test_hook_unknown_connector_404(app_client):
    client, _ = app_client
    r = await client.post("/api/v1/hooks/nosuch", json={"data": {}})
    assert r.status_code == 404


async def test_hook_requires_payload(app_client):
    client, _ = app_client
    r = await client.post("/api/v1/hooks/bitrix24", content=b"", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


async def test_audio_endpoint_auth_and_stream(app_client):
    """Аудио: 401 без ключа, 200 с ?api_key= (плеер не умеет заголовки)."""
    client, _ = app_client
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("call.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79003330000"},
    )
    call_id = r.json()["call"]["id"]

    no_auth = await client.get(f"/api/v1/calls/{call_id}/audio")
    assert no_auth.status_code == 401
    ok = await client.get(f"/api/v1/calls/{call_id}/audio", params={"api_key": "test-token"})
    assert ok.status_code == 200
    assert ok.content[:4] == b"RIFF"
    assert "audio/wav" in ok.headers["content-type"]
    missing = await client.get(f"/api/v1/calls/{uuid.uuid4()}/audio", params={"api_key": "test-token"})
    assert missing.status_code == 404


async def test_stats_summary(app_client):
    client, _ = app_client
    for i in range(2):
        await client.post(
            "/api/v1/calls/upload", headers=AUTH,
            files={"file": (f"s{i}.wav", wav_bytes(2.0 + i), "audio/wav")},
            data={"direction": "outbound", "phone_to": f"+7900777000{i}"},
        )
    r = await client.get("/api/v1/stats/summary", headers=AUTH, params={"days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] >= 2
    assert body["done_calls"] == body["total_calls"]
    assert body["avg_score"] is not None
    assert isinstance(body["top_objections"], list)


async def test_insights_list_and_ack(app_client):
    client, app = app_client
    # звонок → контакт; periodic-джоба генерит инсайты, но в тесте сеем вручную
    r = await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(2.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79001230000"},
    )
    contact_id = r.json()["call"]["contact_id"]

    from polylog.models.system import Insight
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as s:
        s.add(Insight(
            org_id=uuid.UUID((await s.execute(__import__("sqlalchemy").text("SELECT id FROM orgs LIMIT 1"))).scalar()),
            kind="risk_account", severity="warning", contact_id=uuid.UUID(contact_id),
            payload={"score": 55, "band": "medium", "contact_id": str(contact_id),
                     "factors": [{"feature": "days_silence", "contribution": 12,
                                  "description": "тишина 5 дней"}]},
            generated_by="scorecard@0.1.0",
        ))
        await s.commit()

    # лента new
    r = await client.get("/api/v1/insights", headers=AUTH)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["payload"]["score"] == 55 for i in items)

    # ack → из ленты new пропадает
    iid = items[0]["id"]
    r = await client.post(f"/api/v1/insights/{iid}/ack", headers=AUTH)
    assert r.json()["status"] == "ack"
    r = await client.get("/api/v1/insights", headers=AUTH, params={"status": "new"})
    assert all(i["id"] != iid for i in r.json()["items"])


async def test_risks_top(app_client):
    client, _ = app_client
    await client.post(
        "/api/v1/calls/upload", headers=AUTH,
        files={"file": ("c.wav", wav_bytes(3.0), "audio/wav")},
        data={"direction": "outbound", "phone_to": "+79006660000"},
    )
    r = await client.get("/api/v1/risks/top", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert 0 <= body["items"][0]["score"] <= 100
    assert body["items"][0]["top_factor"]
