"""AI Lab (ТЗ v3.0 Часть 2): санитайзер ПДн, сборка контекста, /api/v1/ai/*,
MCP-сервер (JSON-RPC HTTP + tools/call с реальными данными)."""


import json
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

import httpx
from conftest import AUTH

from polylog.graph.service import get_default_org
from polylog.pii.sanitizer import PiiSanitizer, PiiSanitizerConfig

# ── Unit: санитайзер ──


def test_passport_detected_10_digits():
    """BUG-01: серия+номер = 10 цифр, с разделителями и без."""
    from polylog.pii.detect import detect_pii

    for value in ("45 10 123456", "4510 123456"):
        spans = detect_pii(f"Паспорт {value} выдан ОВД")
        assert any(s.kind == "passport" for s in spans), value


def test_sanitize_phones_consistent_across_formats():
    """Один номер в разных форматах → один алиас [ТЕЛЕФОН_1]."""
    s = PiiSanitizer()
    t1 = s.sanitize_text("Звоните на +7 900 111-22-33 сегодня.")
    t2 = s.sanitize_text("Номер: 8 (900) 111-22-33, ждём.")
    assert "[ТЕЛЕФОН_1]" in t1 and "[ТЕЛЕФОН_1]" in t2
    assert "900" not in t1 and "900" not in t2


def test_sanitize_two_phones_two_aliases():
    s = PiiSanitizer()
    t = s.sanitize_text("Телефон 1: +7 900 111-22-33, телефон 2: +7 903 555-66-77")
    assert "[ТЕЛЕФОН_1]" in t and "[ТЕЛЕФОН_2]" in t


def test_sanitize_names_and_orders():
    s = PiiSanitizer()
    t1 = s.sanitize_text("Иванов Иван Иванович, заказ № 45120")
    t2 = s.sanitize_text("с Иванов Иван Иванович по договору 124/26")
    assert "[ФИО_1]" in t1 and "Иванов" not in t1
    assert "[ФИО_1]" in t2, "одно имя → один алиас"
    assert "[ЗАКАЗ_ДОГОВОР_1]" in t1 and "[ЗАКАЗ_ДОГОВОР_2]" in t2


def test_sanitize_intro_name_and_passport_and_snils():
    s = PiiSanitizer()
    t = s.sanitize_text("Меня зовут Ирина, паспорт 45 10 123456, СНИЛС 112-233-445 95")
    assert "Меня зовут" in t and "Ирина" not in t
    assert "123456" not in t and "112-233-445" not in t


def test_sanitize_custom_stop_words():
    s = PiiSanitizer(PiiSanitizerConfig(custom_stop_words=["Ромашка"]))
    t = s.sanitize_text("Проект Ромашка, менеджер Сергей Петрович")
    assert "[СТОП_1]" in t and "Ромашка" not in t


def test_sanitize_disabled_leaves_text():
    s = PiiSanitizer(PiiSanitizerConfig(enabled=False))
    t = s.sanitize_text("Телефон +7 900 111-22-33, Иванов Иван Иванович")
    assert "+7 900 111-22-33" in t and "Иванов" in t


def test_sanitize_uuid_registered_becomes_call_alias():
    """register_id('call', uuid) → тот же алиас заменяет UUID в тексте."""
    s = PiiSanitizer()
    real = "8d380ab5-3401-4a3b-9d1e-2f7a9b0c1d2e"
    alias = s.register_id("call", real)
    assert alias == "[CALL_#1]"
    t = s.sanitize_text(f"Смотри звонок {real} в отчёте")
    assert alias in t and real not in t


def test_sanitize_stats_and_alias_map():
    s = PiiSanitizer()
    s.sanitize_text("Иванов Иван Иванович оставил +7 900 111-22-33 по заказу 45120")
    st = s.stats
    assert st.total_redactions == 3
    assert st.by_category["names"] == 1
    assert st.by_category["phones_emails"] == 1
    assert st.by_category["orders_contracts"] == 1
    assert "[ФИО_1]" in st.alias_map and st.alias_map["[ФИО_1]"] == "Иванов Иван Иванович"


def test_sanitize_obj_recursive():
    s = PiiSanitizer()
    out = s.sanitize_obj({"a": "Позвони +7 900 111-22-33", "b": ["Иванов Иван Иванович", 5]})
    assert "[ТЕЛЕФОН_1]" in out["a"] and "[ФИО_1]" in out["b"][0]


def test_sanitize_phone_metadata_matches_text_alias():
    """sanitize_phone (phone_from) и телефон в тексте → один алиас."""
    s = PiiSanitizer()
    meta = s.sanitize_phone("+7 900 111-22-33")
    text = s.sanitize_text("набран 8 (900) 111-22-33")
    assert meta == text.strip().split()[-1] or (meta == "[ТЕЛЕФОН_1]" and "[ТЕЛЕФОН_1]" in text)


# ── API: предпросмотр, анализ, история, MCP ──


async def _seed(app) -> dict:
    """Звонок с ПДн в тексте, контактом-«рисковым», скором и возражением."""
    from polylog.models.calls import Call, CallSegment, Objection, Score, Violation
    from polylog.models.graph import Contact
    from polylog.models.system import User

    sm = app.state.sessionmaker
    async with sm() as s:
        org = await get_default_org(s)
        agent = User(
            org_id=org.id, email="anna@polylog.local", display_name="Анна Смирнова",
            role="agent", agent_ext_ids=["101"], password_hash=None, is_active=True,
        )
        s.add(agent)
        await s.flush()
        contact = Contact(org_id=org.id, display_name="Иван Петрович")
        s.add(contact)
        await s.flush()
        # рисковый контакт: 20 дней тишины + пропущенный + неотработанное возражение → high
        risky = Call(
            org_id=org.id, direction="outbound", phone_from="101", phone_to="+79001112233",
            agent_user_id=agent.id, contact_id=contact.id, state="done",
            duration_sec=3, started_at=datetime.now(UTC) - timedelta(days=20),
        )
        s.add(risky)
        await s.flush()
        # звонок с ПДн и низким скором
        call = Call(
            org_id=org.id, direction="inbound", phone_from="+79001112233", phone_to="101",
            agent_user_id=agent.id, contact_id=contact.id, state="done",
            duration_sec=95, started_at=datetime.now(UTC) - timedelta(days=2),
        )
        s.add(call)
        await s.flush()
        s.add(CallSegment(call_id=call.id, idx=0, speaker="client", start_ms=0, end_ms=6000,
                          text="Меня зовут Иван Петрович, вопрос по заказу № 45120"))
        s.add(CallSegment(call_id=call.id, idx=1, speaker="agent", start_ms=7000, end_ms=12000,
                          text="Здравствуйте! Ваш номер +7 900 111-22-33, договор 124/26?"))
        s.add(Score(call_id=call.id, rubric_id=uuid_mod.uuid4(), rubric_version=1,
                    total=42.5, items=[], scorer_version="test"))
        s.add(Objection(call_id=call.id, type="price", span_text="это дорого",
                        response_status="failed", confidence=0.9, model_id="rules-test"))
        s.add(Violation(call_id=call.id, kind="crit.question_ignored",
                        span_text="вопрос клиента без ответа", model_id="nli-test"))
        await s.commit()
        return {"call_id": str(call.id), "agent_id": str(agent.id)}


def _mock_llm(handler):
    """MockTransport для подмены LLM-эндпоинта в analyze."""
    return httpx.MockTransport(handler)


async def test_preview_context_sanitizes_pii(app_client):
    client, app = app_client
    seed = await _seed(app)
    r = await client.post(
        "/api/v1/ai/preview-context", headers=AUTH,
        json={"mode": "rubert_scores", "days": 30, "limit_calls": 10},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calls_matched"] == 2
    assert body["pii_stats"]["total_redactions"] > 0
    assert "[ФИО_1]" in body["context_preview"]
    assert "Иван Петрович" not in body["context_preview"]
    # телефон живёт в структурном пакете (rubert-режим не печатает номера)
    assert "[ТЕЛЕФОН_1]" in json.dumps(body["structured_bundle"], ensure_ascii=False)
    assert "[CALL_#1]" in body["structured_bundle"]["calls"][0]["call_id"]
    assert "[CALL_#1]" in body["context_preview"]  # UUID в заголовке → алиас
    # alias_map → реальный UUID звонка
    assert seed["call_id"] in list(body["pii_stats"]["alias_map"].values())


async def test_preview_context_rbac_agent_forbidden(app_client):
    client, app = app_client
    r = await client.post(
        "/api/v1/users", headers=AUTH,
        json={"email": "agent2@polylog.local", "display_name": "Агент",
              "password": "secret123", "role": "agent"},
    )
    assert r.status_code == 200
    login = await client.post(
        "/api/v1/auth/login", json={"email": "agent2@polylog.local", "password": "secret123"}
    )
    token = login.json()["access_token"]
    r = await client.post(
        "/api/v1/ai/preview-context",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "rubert_scores"},
    )
    assert r.status_code == 403


async def test_analyze_with_mock_llm_saves_run(app_client):
    client, app = app_client
    seed = await _seed(app)

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["model"] = payload["model"]
        seen["user"] = payload["messages"][1]["content"]
        # ПДн не утекают в промпт
        assert "Иван Петрович" not in payload["messages"][1]["content"]
        assert "[ФИО_1]" in payload["messages"][1]["content"]
        assert request.headers.get("authorization") == "Bearer sk-test-123"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "# Отчёт ИИ\n\nПроблемы выявлены."}}],
                  "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}},
        )

    app.state.llm_transport = _mock_llm(handler)
    r = await client.post(
        "/api/v1/ai/analyze", headers=AUTH,
        json={
            "mode": "rubert_scores", "days": 30, "limit_calls": 10,
            "api_key": "sk-test-123", "model": "anthropic/claude-3.7-sonnet",
            "user_prompt": "Разбери ошибки менеджеров",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result_markdown"].startswith("# Отчёт ИИ")
    assert body["token_usage"]["total_tokens"] == 150
    assert body["calls_count"] == 2
    assert seed["call_id"] in body["alias_map"].values()

    # история и детали
    runs = (await client.get("/api/v1/ai/runs", headers=AUTH)).json()["items"]
    assert len(runs) == 1 and runs[0]["status"] == "done"
    detail = (await client.get(f"/api/v1/ai/runs/{runs[0]['id']}", headers=AUTH)).json()
    assert detail["result_markdown"].startswith("# Отчёт ИИ")
    assert detail["pii_config"]["stats"]["total_redactions"] > 0


async def test_analyze_llm_error_recorded(app_client):
    client, app = app_client
    await _seed(app)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    app.state.llm_transport = _mock_llm(handler)
    r = await client.post(
        "/api/v1/ai/analyze", headers=AUTH,
        json={"mode": "rubert_scores", "api_key": "sk-bad", "model": "m",
              "user_prompt": "тест"},
    )
    assert r.status_code == 502
    runs = (await client.get("/api/v1/ai/runs", headers=AUTH)).json()["items"]
    assert runs and runs[0]["status"] == "failed"
    assert "401" in (runs[0]["error_message"] or "")


async def test_analyze_requires_prompt_and_key(app_client):
    client, app = app_client
    await _seed(app)
    # нет промпта
    r = await client.post("/api/v1/ai/analyze", headers=AUTH,
                          json={"mode": "rubert_scores", "api_key": "k", "model": "m"})
    assert r.status_code == 422
    # нет ключа нигде
    r = await client.post("/api/v1/ai/analyze", headers=AUTH,
                          json={"mode": "rubert_scores", "model": "m", "user_prompt": "x"})
    assert r.status_code == 422


async def test_mcp_rpc_full_flow(app_client):
    """initialize → tools/list → tools/call (problematic_calls) →
    call_details по алиасу [CALL_#1] из реестра сессии."""
    client, app = app_client
    await _seed(app)

    async def rpc(method, params=None, id_=1):
        r = await client.post(
            "/api/v1/mcp/rpc", headers=AUTH,
            json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
        )
        return r

    r = await rpc("initialize", id_=1)
    assert r.status_code == 200
    info = r.json()["result"]["serverInfo"]
    assert info["name"] == "polylog-analytics"

    r = await rpc("tools/list", id_=2)
    names = [t["name"] for t in r.json()["result"]["tools"]]
    assert len(names) == 5 and "polylog_get_problematic_calls" in names

    r = await rpc("tools/call", {"name": "polylog_get_problematic_calls",
                                 "arguments": {"days": 30, "risk_band": "medium"}}, id_=3)
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    text = result["content"][0]["text"]
    assert "[CALL_#1]" in text and "+79001112233" not in text

    # алиас из предыдущего вызова резолвится в реестре сессии
    r = await rpc("tools/call", {"name": "polylog_get_call_details",
                                 "arguments": {"call_id": "[CALL_#1]"}}, id_=4)
    result = r.json()["result"]
    assert result["isError"] is False, result["content"][0]["text"]
    data = json.loads(result["content"][0]["text"])
    assert data.get("call_alias") == "[CALL_#1]"
    assert "Меня зовут" in data["segments"][0]["text"]

    # неизвестный метод → ошибка -32601
    r = await rpc("nope/method", id_=5)
    assert r.json()["error"]["code"] == -32601


async def test_mcp_transcripts_and_coaching_tools(app_client):
    client, app = app_client
    await _seed(app)

    r = await client.post(
        "/api/v1/mcp/rpc", headers=AUTH,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "polylog_get_transcripts_by_period",
                         "arguments": {"date_from": None, "date_to": None, "days": 30}}},
    )
    assert r.status_code == 200
    text = r.json()["result"]["content"][0]["text"]
    assert "[00:00] Клиент:" in text and "Иван Петрович" not in text
    assert "[ЗАКАЗ_ДОГОВОР_1]" in text

    r = await client.post(
        "/api/v1/mcp/rpc", headers=AUTH,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "polylog_get_team_coaching_summary",
                         "arguments": {"days": 30}}},
    )
    text2 = r.json()["result"]["content"][0]["text"]
    assert "| Менеджер" in text2 and "Анна Смирнова" not in text2


async def test_mcp_config_endpoint(app_client):
    client, app = app_client
    r = await client.get("/api/v1/ai/mcp-config", headers=AUTH, params={"sanitize_pii": True})
    assert r.status_code == 200
    body = r.json()
    assert set(body["harnesses"]) >= {"claude_code", "codex", "zcode", "cursor", "claude_desktop"}
    assert "--sanitize-pii" in body["harnesses"]["claude_code"]["cli_command"]
    assert body["harnesses"]["claude_code_http"]["mcp_json"]["mcpServers"]["polylog"]["type"] == "sse"
    assert len(body["tools"]) == 5


async def test_ai_presets_endpoint(app_client):
    client, app = app_client
    r = await client.get("/api/v1/ai/presets", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert len(body["presets"]) == 5
    assert body["presets"][0]["system_prompt"]
    assert len(body["recommended_models"]) >= 4
