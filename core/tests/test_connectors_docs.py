"""Коннекторы amoCRM/Bitrix24 по официальным форматам API (фикстуры без сети).

Источники форматов:
- amoCRM: https://www.amocrm.ru/developers/content/crm_platform/calls-api («Добавление звонков»),
  oAuth 2.0 раздел;
- Bitrix24: https://apidocs.bitrix24.com/api-reference/telephony/voximplant/voximplant-statistic-get.html
"""

from datetime import UTC, datetime

import httpx

from polylog.ingest.amocrm import (
    AmoCRMConnector,
    AmoOAuth,
    build_publish_body,
    parse_call_element,
)
from polylog.ingest.bitrix24 import Bitrix24Connector, parse_statistic_row
from polylog.ingest.registry import get_connector

# --- Bitrix24 voximplant.statistic.get (реальные поля из apidocs) ---

B24_ROW = {
    "ID": 145,
    "CALL_ID": "a9f3c0f1-7c2f-4f39-9c11-0b5b8e4d2a10",
    "EXTERNAL_CALL_ID": "ext-77",
    "CALL_TYPE": 2,
    "PORTAL_USER_ID": 12,
    "PORTAL_NUMBER": "+74950000000",
    "PHONE_NUMBER": "+7 903 111-22-33",
    "CALL_DURATION": 87,
    "CALL_START_DATE": "2026-10-01T12:00:00+03:00",
    "CALL_RECORD_URL": "https://company.bitrix24.ru/records/a9f3.mp3",
    "RECORD_FILE_ID": 981,
    "CALL_FAILED_CODE": "200",
    "CRM_ENTITY_TYPE": "CONTACT",
    "CRM_ENTITY_ID": 4321,
}


def test_b24_statistic_row_inbound():
    ref = parse_statistic_row(B24_ROW)
    assert ref is not None
    assert ref.external_id == "b24-a9f3c0f1-7c2f-4f39-9c11-0b5b8e4d2a10"
    assert ref.direction == "inbound"  # CALL_TYPE=2
    assert ref.duration_sec == 87
    assert ref.started_at == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert ref.recording_uri == "https://company.bitrix24.ru/records/a9f3.mp3"
    assert ref.disposition == "ANSWERED"
    assert ref.crm_refs["entity_type"] == "CONTACT"


def test_b24_row_outbound_and_missed():
    out = parse_statistic_row({**B24_ROW, "CALL_TYPE": 1, "CALL_FAILED_CODE": "304"})
    assert out is not None and out.direction == "outbound"
    assert out.disposition == "FAILED_304"
    assert parse_statistic_row({**B24_ROW, "CALL_DURATION": 0}) is None  # пропущенный


def test_b24_client_pagination_mock():
    """Пагинация next по 50 (официальная схема): 2 страницы → 3 CallRef."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/rest/7/KEY/voximplant.statistic.get" in str(request.url)
        body = request.read().decode()
        if b'"start":0' in request.read() or '"start": 0' in body or "start" in body:
            pass
        page = 1 if b"voximplant" in request.url.path.encode() else 1
        del page
        payload = request.content
        if b'"start": 0' in payload or b'"start":0' in payload:
            return httpx.Response(200, json={
                "result": [dict(B24_ROW, CALL_ID=f"call-{i}") for i in range(50)],
                "total": 52, "next": 50,
            })
        return httpx.Response(200, json={
            "result": [dict(B24_ROW, CALL_ID=f"call-{i}") for i in range(50, 52)],
            "total": 52, "next": None,
        })

    conn = Bitrix24Connector(portal="company.bitrix24.ru", user_id="7", webhook_key="KEY",
                             transport=httpx.MockTransport(handler))
    refs = conn.get_calls(since=datetime(2026, 9, 1, tzinfo=UTC), limit=100)
    assert len(refs) == 52
    assert refs[0].external_id == "b24-call-0" and refs[-1].external_id == "b24-call-51"


def test_b24_webhook_mode_via_registry():
    hook = get_connector("bitrix24", {})
    assert hasattr(hook, "parse")
    pull = get_connector("bitrix24", {"portal": "company.bitrix24.ru",
                                      "user_id": "1", "webhook_key": "abc"})
    assert isinstance(pull, Bitrix24Connector)


# --- amoCRM v4 ---

AMO_ITEM = {
    "id": 1001,
    "entity_type": "contact",
    "entity_id": 55001,
    "phone": "+7 903 111-22-33",
    "source": "telphin",
    "uniq": "a9f3",
    "duration": 60,
    "link": "https://amo-crm-cdn.example/mp3/1001.mp3",
    "direction": "inbound",
    "call_result": None,
    "call_status": 4,
    "created_at": 1727776800,
}


def test_amo_call_element_parse():
    ref = parse_call_element(AMO_ITEM)
    assert ref is not None
    assert ref.external_id == "amo-1001"
    assert ref.direction == "inbound" and ref.phone_from == "+7 903 111-22-33"
    assert ref.duration_sec == 60
    assert ref.crm_refs["entity_type"] == "contact"
    assert ref.started_at == datetime(2024, 10, 1, 10, 0, tzinfo=UTC)


def test_amo_publish_body_per_docs():
    """Тело POST /api/v4/calls: direction/duration/source/phone — обязательные."""
    body = build_publish_body(direction="outbound", duration_sec=124,
                              phone="+79001234567", uniq="polylog-abc",
                              link="https://storage/call.wav")
    assert body["direction"] == "outbound" and body["duration"] == 124
    assert body["source"] == "polylog" and body["uniq"] == "polylog-abc"
    try:
        build_publish_body(direction="sideways", duration_sec=1, phone="1")
        raise AssertionError("ожидался ConnectorError")
    except Exception as e:
        assert "inbound|outbound" in str(e)


def test_amo_get_contacts_pagination_mock():
    """GET /api/v4/contacts (граф Customer 360) + обязат. User-Agent."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v4/contacts" in str(request.url)
        assert request.headers["Authorization"] == "Bearer token-x"
        assert "polylog" in request.headers["User-Agent"], "amoCRM требует User-Agent"
        return httpx.Response(200, json={"_embedded": {"contacts": [
            {"id": 3426897, "name": "Иван Петров",
             "custom_fields_values": [{"field_code": "PHONE",
                                       "values": [{"value": "+79001112233"}]}]},
        ]}})

    conn = AmoCRMConnector(subdomain="demo", access_token="token-x",
                           transport=httpx.MockTransport(handler))
    contacts = conn.get_contacts(limit=10)
    assert contacts[0]["name"] == "Иван Петров"


def test_amo_publish_mock():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = httpx.Response(200, json={"_embedded": {"calls": [{"id": 1}]}})
        del request
        return body

    conn = AmoCRMConnector(subdomain="demo", access_token="t",
                           transport=httpx.MockTransport(handler))
    res = conn.publish_call(build_publish_body(direction="inbound", duration_sec=30, phone="+79000000000"))
    assert res["_embedded"]["calls"][0]["id"] == 1


def test_amo_oauth_authorize_url():
    oauth = AmoOAuth(client_id="cid", client_secret="sec")
    url = oauth.authorize_url("demo")
    assert url.startswith("https://demo.amocrm.ru/oauth?")
    assert "client_id=cid" in url and "mode=post_message" in url
