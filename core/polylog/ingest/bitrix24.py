"""Битрикс24 коннектор (doc 02 §1.2) — по официальной документации
https://apidocs.bitrix24.com/api-reference/telephony/ (переработан 2026-10-04).

Три режима:

1. **Webhook** — локальное приложение шлёт `onVoximplantCallEnd` на
   `POST /api/v1/hooks/bitrix24` (парсинг payload → CallRef, реализовано).
2. **Pull (webhook-ключ)** — `voximplant.statistic.get` через
   `https://{portal}/rest/{user_id}/{webhook_key}/{method}` — самый простой
   прод-вариант для входящих данных.
3. **Pull (OAuth)** — тот же метод с Bearer-токеном приложения.

Спецификация voximplant.statistic.get (официальные доки):
- поля: CALL_ID, EXTERNAL_CALL_ID, CALL_TYPE (1=исходящий, 2=входящий,
  3=входящий с переадресацией, 4=callback, 5=информационный), PHONE_NUMBER,
  CALL_DURATION, CALL_START_DATE (ISO-8601), CALL_RECORD_URL (готовый URL
  записи), RECORD_FILE_ID, CALL_FAILED_CODE (200=успех, 304=пропущен, 603=отклонён…),
  CRM_ENTITY_TYPE (CONTACT|COMPANY|LEAD), CRM_ENTITY_ID, PORTAL_USER_ID;
- пагинация: `start` (по 50 записей), фильтр `FILTER[">=CALL_START_DATE"]`.
Запись: приоритет CALL_RECORD_URL; файл по RECORD_FILE_ID — через диск (M2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from polylog.ingest.base import CallRef, ConnectorError

_CALL_TYPE_DIRECTION = {
    1: "outbound",
    2: "inbound",
    3: "inbound",  # с переадресацией
    4: "outbound",  # callback — инициирован порталом
    5: "internal",
}


def parse_statistic_row(row: dict[str, Any]) -> CallRef | None:
    """Элемент result[] от voximplant.statistic.get → CallRef."""
    call_id = str(row.get("CALL_ID") or "")
    if not call_id:
        return None
    duration = int(row.get("CALL_DURATION") or 0)
    if duration <= 0:
        return None  # пропущенные без разговора не анализируем
    try:
        call_type = int(row.get("CALL_TYPE") or 0)
    except (TypeError, ValueError):
        call_type = 0
    direction = _CALL_TYPE_DIRECTION.get(call_type, "outbound")

    started = None
    ts = row.get("CALL_START_DATE")
    if ts:
        try:
            started = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            started = None

    phone = (row.get("PHONE_NUMBER") or "").strip() or None
    record_url = row.get("CALL_RECORD_URL") or None
    failed_code = str(row.get("CALL_FAILED_CODE") or "200")

    return CallRef(
        external_id=f"b24-{call_id}",
        started_at=started or datetime.now(UTC),
        duration_sec=duration,
        direction=direction,
        phone_from=phone if direction == "inbound" else None,
        phone_to=phone if direction != "inbound" else None,
        recording_uri=record_url,
        consent_flag=True,
        disposition="ANSWERED" if failed_code == "200" else f"FAILED_{failed_code}",
        crm_refs={"system": "bitrix24",
                  "entity_type": row.get("CRM_ENTITY_TYPE"),
                  "entity_id": row.get("CRM_ENTITY_ID"),
                  "portal_user_id": row.get("PORTAL_USER_ID"),
                  "record_file_id": row.get("RECORD_FILE_ID")},
    )


def parse_event_payload(payload: dict[str, Any]) -> CallRef | None:
    """Webhook `onVoximplantCallEnd` → CallRef (толерантный парсинг полей)."""
    data = payload.get("data", payload)
    call = data.get("CALL", data)
    call_id = str(call.get("CALL_ID") or call.get("ID") or "")
    if not call_id:
        return None
    duration = int(float(call.get("CALL_DURATION") or call.get("DURATION") or 0))
    if duration <= 0:
        return None
    ts_raw = call.get("CALL_START_DATE") or call.get("START_DATE")
    started = None
    if ts_raw:
        try:
            started = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            started = None
    direction = str(call.get("CALL_DIRECTION") or call.get("DIRECTION") or "outbound").lower()
    phone = call.get("PHONE_NUMBER") or call.get("PHONE") or None
    record_url = call.get("CALL_RECORD_URL") or call.get("RECORD_URL") or None
    if record_url and not str(record_url).startswith("http"):
        record_url = None  # fileId требует REST-подписи — конвертация через клиент

    return CallRef(
        external_id=f"b24-{call_id}",
        started_at=started or datetime.now(UTC),
        duration_sec=duration,
        direction=direction if direction in ("inbound", "outbound", "internal") else "outbound",
        phone_from=phone if direction == "inbound" else None,
        phone_to=phone if direction != "inbound" else None,
        recording_uri=record_url,
        consent_flag=True,
        crm_refs={"system": "bitrix24", "entity_id": call.get("CRM_ENTITY_ID"),
                  "contact_id": call.get("CONTACT_ID")},
    )


class Bitrix24Connector:
    """Pull-клиент voximplant.statistic.get. Webhook-ключ ИЛИ OAuth-токен."""

    id = "bitrix24"

    def __init__(
        self,
        portal: str = "",  # например "company.bitrix24.ru"
        user_id: str = "1",  # для webhook-режима
        webhook_key: str = "",
        oauth_token: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not portal:
            raise ConnectorError("нужен portal (company.bitrix24.ru)")
        if not webhook_key and not oauth_token:
            raise ConnectorError("нужен webhook_key ИЛИ oauth_token")
        self.portal = portal.rstrip("/")
        self._webhook = f"/rest/{user_id}/{webhook_key}" if webhook_key else "/rest"
        self._oauth = oauth_token
        self._transport = transport

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self._oauth}"} if self._oauth else {}
        return httpx.Client(
            base_url=f"https://{self.portal}",
            headers=headers,
            timeout=30,
            transport=self._transport,
        )

    def _method(self, client: httpx.Client, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = client.post(f"{self._webhook}/{method}", json=payload)
        r.raise_for_status()
        return r.json()

    def verify(self) -> dict[str, Any]:
        try:
            with self._client() as c:
                data = self._method(c, "voximplant.statistic.get",
                                    {"FILTER": {}, "SORT": "ID", "ORDER": "ASC", "start": 0})
            return {"ok": "result" in data, "total": data.get("total")}
        except httpx.HTTPError as e:
            return {"ok": False, "error": str(e)}

    def get_calls(self, since: datetime, limit: int = 100) -> list[CallRef]:
        """voximplant.statistic.get с фильтром по дате и пагинацией next (по 50)."""
        refs: list[CallRef] = []
        start = 0
        since_str = since.astimezone(UTC).isoformat()
        with self._client() as c:
            while len(refs) < limit:
                data = self._method(c, "voximplant.statistic.get", {
                    "FILTER": {">=CALL_START_DATE": since_str},
                    "SORT": "ID", "ORDER": "ASC", "start": start,
                })
                rows = data.get("result", [])
                if not rows:
                    break
                for row in rows:
                    ref = parse_statistic_row(row)
                    if ref:
                        refs.append(ref)
                nxt = data.get("next")
                if nxt is None or len(refs) >= limit:
                    break
                start = nxt
        return refs[:limit]

    def download(self, ref: CallRef) -> bytes:
        if not ref.recording_uri:
            raise ConnectorError(f"у звонка {ref.external_id} нет записи (CALL_RECORD_URL)")
        # CALL_RECORD_URL — подписанный URL портала
        r = httpx.get(ref.recording_uri, timeout=120, follow_redirects=True)
        r.raise_for_status()
        return r.content
