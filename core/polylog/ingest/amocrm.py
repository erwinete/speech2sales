"""amoCRM коннектор (doc 02 §1.2) — по официальной документации
https://www.amocrm.ru/developers/content/crm_platform/ (v4; переработан 2026-10-04).

Два режима по официальной спецификации:

1. **Pull** — GET /api/v4/calls: чтение звонков, добавленных интеграциями
   телефонии заказчика (пагинация page/limit, направление in|out).
2. **Push** — POST /api/v4/calls (раздел «Добавление звонков»): публикация
   анализируемых звонков в amoCRM; система сама привязывает звонок к
   контакту/компании/сделке по последним 10 цифрам номера. Поля: direction
   (обяз.), duration (обяз.), source (обяз.), phone (обяз.), uniq, link
   (URL записи), call_result, call_status (1–7), call_responsible.

Авторизация — OAuth 2.0 (раздел oAuth 2.0): authorization code + refresh, либо
**long-lived токен** приватной интеграции (вставляется в конфиг без танца).
Пароль пользователя в API v4 не используется.
Скрипт авторизации для демо-аккаунта: tools/connectors/amocrm_oauth.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from polylog.ingest.base import CallRef, ConnectorError

OAUTH_TOKEN_URL = "https://www.amocrm.ru/oauth2/access_token"


def parse_call_element(item: dict[str, Any]) -> CallRef | None:
    """Элемент GET /api/v4/calls → CallRef (v4: direction in|out, duration, link)."""
    call_id = str(item.get("id") or "")
    if not call_id:
        return None
    duration = int(item.get("duration") or 0)
    if duration <= 0:
        return None
    direction = item.get("direction") or "outbound"
    # v4 GET отдаёт in|out; POST принимает inbound|outbound — парсим толерантно
    direction = {"in": "inbound", "inbound": "inbound",
                 "out": "outbound", "outbound": "outbound"}.get(direction, "outbound")
    started = None
    ts = item.get("created_at")
    if ts:
        try:
            started = datetime.fromtimestamp(int(ts), tz=UTC)
        except (ValueError, OSError, OverflowError):
            started = None
    phone = item.get("phone") or None
    return CallRef(
        external_id=f"amo-{call_id}",
        started_at=started or datetime.now(UTC),
        duration_sec=duration,
        direction=direction,
        phone_from=phone if direction == "inbound" else None,
        phone_to=phone if direction != "inbound" else None,
        recording_uri=item.get("link") or None,
        consent_flag=True,
        disposition=str(item["call_status"]) if item.get("call_status") else "ANSWERED",
        crm_refs={"system": "amocrm", "entity_type": item.get("entity_type"),
                  "entity_id": item.get("entity_id")},
    )


def build_publish_body(
    *, direction: str, duration_sec: int, phone: str, source: str = "polylog",
    uniq: str | None = None, link: str | None = None, call_result: str | None = None,
) -> dict[str, Any]:
    """Тело POST /api/v4/calls («Добавление звонков») из нашего звонка.
    Автопривязка в amo: по последним 10 цифрам phone → контакт/компания/сделка."""
    if direction not in ("inbound", "outbound"):
        raise ConnectorError(f"direction={direction!r}: допустимо inbound|outbound")
    if duration_sec <= 0 or not phone:
        raise ConnectorError("нужны duration > 0 и phone")
    body: dict[str, Any] = {
        "direction": direction,
        "duration": int(duration_sec),
        "phone": phone,
        "source": source,
    }
    if uniq:
        body["uniq"] = uniq  # идемпотентность на стороне amo
    if link:
        body["link"] = link
    if call_result:
        body["call_result"] = call_result
    return body


class AmoOAuth:
    """OAuth 2.0 amoCRM (официальный раздел oAuth 2.0)."""

    def __init__(self, client_id: str = "", client_secret: str = "",
                 redirect_uri: str = "https://polylog.local/oauth/amocrm") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorize_url(self, subdomain: str, mode: str = "post_message") -> str:
        from urllib.parse import urlencode

        q = urlencode({
            "client_id": self.client_id,
            "mode": mode,
            "redirect_uri": self.redirect_uri,
        })
        return f"https://{subdomain}.amocrm.ru/oauth?{q}"

    def exchange_code(self, subdomain: str, code: str) -> dict[str, Any]:
        """Authorization code → {access_token, refresh_token, expires_in, ...}."""
        r = httpx.post(OAUTH_TOKEN_URL, json={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }, timeout=30)
        r.raise_for_status()
        return r.json()

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        r = httpx.post(OAUTH_TOKEN_URL, json={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, timeout=30)
        r.raise_for_status()
        return r.json()


class AmoCRMConnector:
    id = "amocrm"

    def __init__(self, subdomain: str = "", access_token: str = "",
                 transport: httpx.BaseTransport | None = None) -> None:
        self.subdomain = subdomain
        self.access_token = access_token
        self._transport = transport  # тесты: MockTransport

    def _client(self) -> httpx.Client:
        # User-Agent ОБЯЗАТЕЛЕН (официальные «Ограничения и рекомендации»):
        # без него data-эндпоинты отвечают 401 «Неверный логин или пароль»
        # (найдено live-тестом 2026-10-04).
        return httpx.Client(
            base_url=f"https://{self.subdomain}.amocrm.ru",
            headers={"Authorization": f"Bearer {self.access_token}",
                     "User-Agent": "polylog/0.1 (speech analytics)"},
            timeout=30,
            transport=self._transport,
        )

    def verify(self) -> dict[str, Any]:
        """GET /api/v4/account — живость токена/домена."""
        try:
            with self._client() as c:
                r = c.get("/api/v4/account")
            return {"ok": r.status_code == 200, "http": r.status_code,
                    "hint": "401 — нужен OAuth/long-lived токен (tools/connectors/amocrm_oauth.py)"}
        except httpx.HTTPError as e:
            return {"ok": False, "error": str(e)}

    def get_contacts(self, limit: int = 100, page: int = 1) -> list[dict[str, Any]]:
        """GET /api/v4/contacts — контакты для графа Customer 360 (телефоны, имя).
        ВНИМАНИЕ: GET /api/v4/calls в amoCRM НЕ существует (405) — звонки только
        пишутся (POST) или читаются из notes/events интеграций телефонии."""
        with self._client() as c:
            r = c.get("/api/v4/contacts", params={"page": page, "limit": min(250, limit)})
            r.raise_for_status()
            return (r.json().get("_embedded") or {}).get("contacts", [])[:limit]

    def get_leads(self, limit: int = 100, page: int = 1) -> list[dict[str, Any]]:
        """GET /api/v4/leads — сделки (название, цена, статус) для риск-фич."""
        with self._client() as c:
            r = c.get("/api/v4/leads", params={"page": page, "limit": min(250, limit)})
            r.raise_for_status()
            return (r.json().get("_embedded") or {}).get("leads", [])[:limit]

    def publish_call(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v4/calls — push-модель (раздел «Добавление звонков»)."""
        with self._client() as c:
            r = c.post("/api/v4/calls", json=[body])  # метод принимает массив
            r.raise_for_status()
            return r.json()

    def download(self, ref: CallRef) -> bytes:
        if not ref.recording_uri:
            raise ConnectorError(f"у звонка {ref.external_id} нет записи")
        # link в v4 — полный URL (обычно CDN с токеном); относительный — через портал
        url = ref.recording_uri
        if not url.startswith("http"):
            url = f"https://{self.subdomain}.amocrm.ru{url}"
        r = httpx.get(url, timeout=120, follow_redirects=True)
        r.raise_for_status()
        return r.content
