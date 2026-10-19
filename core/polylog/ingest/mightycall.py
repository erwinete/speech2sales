"""MightyCall (облачная АТС, популярна у микробизнеса СНГ) — doc 02 §1.2, 2026-10-04.

Модель интеграции: REST API + webhooks. discover() поллит список звонков,
download() качает запись по URL с bearer-токеном. Реализовано с httpx и
инъекцией transport (тесты — MockTransport без сети). Live-ключи — M2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from polylog.ingest.base import CallRef, ConnectorError

DEFAULT_BASE_URL = "https://api.mightycall.io/v1"  # фактический base — из конфига org


def parse_call_json(item: dict[str, Any]) -> CallRef | None:
    """Элемент списка звонков MightyCall → CallRef (по документации API, v0)."""
    call_id = str(item.get("id") or item.get("callId") or "")
    if not call_id:
        return None
    duration = int(item.get("duration") or 0)
    if duration <= 0:
        return None
    started_raw = item.get("startedAt") or item.get("createdAt")
    started = None
    if started_raw:
        try:
            started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
        except ValueError:
            started = None
    direction = item.get("direction") or "outbound"
    return CallRef(
        external_id=f"mc-{call_id}",
        started_at=started or datetime.now(UTC),
        duration_sec=duration,
        direction=direction,
        phone_from=item.get("from") or None,
        phone_to=item.get("to") or None,
        recording_uri=item.get("recordingUrl") or None,
        consent_flag=bool(item.get("recordingConsent", True)),
        disposition=item.get("status") or "ANSWERED",
    )


class MightyCallConnector:
    id = "mightycall"

    def __init__(self, api_key: str = "", base_url: str = DEFAULT_BASE_URL,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._transport = transport  # для тестов

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
            transport=self._transport,
        )

    def verify(self) -> dict[str, Any]:
        try:
            with self._client() as c:
                r = c.get("/calls", params={"limit": 1})
            return {"ok": r.status_code == 200, "http": r.status_code}
        except httpx.HTTPError as e:
            return {"ok": False, "error": str(e)}

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        """Поллинг списка звонков с фильтром по времени."""
        refs: list[CallRef] = []
        offset = 0
        with self._client() as c:
            while len(refs) < limit:
                r = c.get("/calls", params={"limit": min(50, limit - len(refs)), "offset": offset})
                r.raise_for_status()
                items = r.json().get("items", [])
                if not items:
                    break
                for item in items:
                    ref = parse_call_json(item)
                    if ref and ref.started_at >= since:
                        refs.append(ref)
                offset += len(items)
        return refs[:limit]

    def download(self, ref: CallRef) -> bytes:
        if not ref.recording_uri:
            raise ConnectorError(f"у звонка {ref.external_id} нет записи")
        with self._client() as c:
            r = c.get(ref.recording_uri)
            r.raise_for_status()
            return r.content
