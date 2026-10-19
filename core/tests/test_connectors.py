"""Коннекторы телефонии/CRM СНГ: парсинг фикстур без сети (doc 02 §1.2)."""

from datetime import UTC, datetime

import httpx
import pytest

from polylog.ingest.amocrm import parse_call_element
from polylog.ingest.bitrix24 import parse_event_payload
from polylog.ingest.cisco_ucm import parse_cdr_csv
from polylog.ingest.mightycall import parse_call_json
from polylog.ingest.oktell import parse_oktell_row
from polylog.ingest.registry import get_connector

CISCO_CDR = (
    "globalCallID_callId,callingPartyNumber,originalCalledPartyNumber,duration,"
    "dateTimeOrigination,origCause_value\n"
    "7001,101,+79001112233,124,1727769600,0\n"
    "7002,+74955556677,102,58,1727769660,0\n"
    "7003,103,104,0,1727769700,0\n"
)


def test_cisco_cdr_parse():
    refs = parse_cdr_csv(CISCO_CDR, since=datetime(2020, 1, 1, tzinfo=UTC))
    assert len(refs) == 2  # duration=0 отброшен
    out = refs[0]
    assert out.direction == "outbound"  # src — внутренний 101
    assert out.phone_to == "+79001112233"
    assert out.external_id == "cucm-7001"
    assert out.duration_sec == 124


def test_oktell_row_parse():
    ref = parse_oktell_row({
        "CallID": "555", "CallStart": "2026-10-01T12:00:00",
        "PhoneIn": "+79001234567", "PhoneOut": "201", "TalkLen": 95, "LineType": "inbound",
    })
    assert ref is not None
    assert ref.external_id == "oktell-555"
    assert ref.direction == "inbound"
    assert ref.phone_from == "+79001234567"
    assert ref.duration_sec == 95
    assert parse_oktell_row({"CallID": "1", "TalkLen": 0}) is None


def test_mightycall_parse_and_mock_download():
    ref = parse_call_json({
        "id": "mc-9", "duration": 210, "startedAt": "2026-10-01T09:30:00Z",
        "direction": "inbound", "from": "+79005550011", "to": "100",
        "recordingUrl": "https://api.example.test/recordings/9.mp3",
    })
    assert ref is not None and ref.external_id == "mc-mc-9"  # id уже с префиксом mc-

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/recordings/9.mp3" in str(request.url)
        return httpx.Response(200, content=b"RIFFfakeaudio")

    conn = get_connector("mightycall", {"api_key": "k", "base_url": "https://api.example.test/v1"})
    conn._transport = httpx.MockTransport(handler)
    data = conn.download(ref)
    assert data.startswith(b"RIFF")


def test_bitrix24_event_payload():
    ref = parse_event_payload({
        "event": "onVoximplantCallEnd",
        "data": {"CALL": {
            "CALL_ID": "b24-77", "CALL_DURATION": 84, "CALL_DIRECTION": "INBOUND",
            "PHONE_NUMBER": "+79007776655", "CALL_START_DATE": "2026-10-01T10:00:00+03:00",
            "RECORD_URL": "https://portal.bitrix24.ru/record/77.mp3",
            "CONTACT_ID": "c-12", "CRM_ENTITY_ID": "d-5",
        }},
    })
    assert ref is not None
    assert ref.external_id == "b24-b24-77"
    assert ref.direction == "inbound" and ref.phone_from == "+79007776655"
    assert ref.crm_refs["system"] == "bitrix24"

    hook = get_connector("bitrix24", {})
    assert hook.parse({"data": {}}) is None  # без CALL_ID → None


def test_amocrm_element_parse():
    ref = parse_call_element({
        "id": 42, "duration": 63, "direction": "in", "phone": "+79009990000",
        "created_at": 1727769600, "link": "https://cdn.amocrm.ru/rec/42.mp3",
        "entity_type": "contact", "entity_id": 77,
    })
    assert ref is not None
    assert ref.direction == "inbound"
    assert ref.phone_from == "+79009990000"
    assert ref.crm_refs["entity_type"] == "contact" and ref.crm_refs["system"] == "amocrm"


def test_registry_unknown_raises():
    with pytest.raises(Exception, match="не зарегистрирован"):
        get_connector("nonexistent", {})
