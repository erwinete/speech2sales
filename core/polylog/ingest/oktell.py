"""Oktell (Октелл) коннектор — популярная СНГ-АТС (doc 02 §1.2, добавлено 2026-10-04).

Модель интеграции:
- CDR: MS SQL база Октелла (таблицы Calls/Histograms) — читаем через SQLAlchemy
  (mssql+pymssql), поля: CallID, CallStart, PhoneIn/PhoneOut, CallLen, TalkLen.
- Записи: файлы на диске сервера (UNC \\server\Records\) или HTTP по CallID.

Реализовано: парсинг строк CDR (dict) → CallRef + конвертация SQL-строк
(без сети — тесты на фикстурах). Live-SQL — M2 (креды заказчика).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polylog.ingest.base import CallRef, ConnectorError


def parse_oktell_row(row: dict[str, Any]) -> CallRef | None:
    """Строка из таблицы Calls Октелла → CallRef."""
    call_id = str(row.get("CallID") or row.get("id") or "")
    if not call_id:
        return None
    talk_len = int(float(row.get("TalkLen") or row.get("CallLen") or 0))
    if talk_len <= 0:
        return None
    started = row.get("CallStart")
    if isinstance(started, str):
        try:
            started = datetime.fromisoformat(started)
        except ValueError:
            started = None
    if isinstance(started, datetime) and started.tzinfo is None:
        started = started.replace(tzinfo=UTC)

    phone_in = (row.get("PhoneIn") or "").strip()
    phone_out = (row.get("PhoneOut") or "").strip()
    direction = row.get("LineType") or ("inbound" if phone_in and len(phone_in) >= 10 else "outbound")

    return CallRef(
        external_id=f"oktell-{call_id}",
        started_at=started or datetime.now(UTC),
        duration_sec=talk_len,
        direction=direction,
        phone_from=phone_in or None,
        phone_to=phone_out or None,
        recording_uri=row.get("RecordPath") or row.get("RecFile") or None,
        consent_flag=True,
        disposition="ANSWERED" if talk_len > 0 else "NO ANSWER",
    )


class OktellConnector:
    id = "oktell"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def verify(self) -> dict[str, Any]:
        return {
            "ok": bool(self.config.get("dsn")),
            "hint": "нужен dsn (mssql+pymssql://user:pass@oktell-db/oktell) — настраивается в UI (M2)",
        }

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        raise ConnectorError(
            "MS SQL-режим Октелла подключается в M2 live-контуре; "
            "для тестов — parse_oktell_row на фикстурах"
        )

    def download(self, ref: CallRef) -> bytes:
        path = ref.recording_uri
        if path and Path(path).is_file():
            return Path(path).read_bytes()
        raise ConnectorError(f"запись Октелла недоступна: {path!r}")
