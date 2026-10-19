"""Cisco Unified CM / CUBE коннектор (doc 02 §1.2, добавлено 2026-10-04).

Модель интеграции:
- CDR: CUCM пишет flat CDR (csv) на SFTP-сервер (cdr Repository) — коннектор
  читает файлы `cdr_flat_*` и парсит поля originalCalledPartyNumber,
  callingPartyNumber, duration, globalCallID_callId.
- Записи: Cisco Unified Recording / MediaSense отдают WAV по URL из CDR
  (поле fileDurationTime + имя записи) — для wall-инсталляций чаще SFTP-каталог.

Реализовано: парсинг CDR-CSV → CallRef (без сети — тесты на фикстурах).
Сеть (SFTP/http) — `--live` контур M2, требует кредов заказчика.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polylog.ingest.base import CallRef, ConnectorError


def parse_cdr_csv(content: str, since: datetime | None = None) -> list[CallRef]:
    """Cisco flat CDR CSV → CallRef. Разделитель ',', первая строка — заголовок."""
    refs: list[CallRef] = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        try:
            duration = int(float(row.get("duration", 0) or 0))
        except ValueError:
            duration = 0
        epoch = row.get("globalCallID_callId") or row.get("callIdentifier") or ""
        ts_raw = row.get("dateTimeOrigination") or row.get("dateTimeConnect")
        started = _epoch_to_utc(ts_raw)
        if since and started and started < since:
            continue
        if duration <= 0:
            continue  # без длительности — пропущенный/незавершённый
        src = (row.get("callingPartyNumber") or "").strip()
        dst = (row.get("originalCalledPartyNumber") or "").strip()
        refs.append(
            CallRef(
                external_id=f"cucm-{epoch or hash((src, dst, started))}",
                started_at=started or datetime.now(UTC),
                duration_sec=duration,
                direction="outbound" if _looks_ext(src) else "inbound",
                phone_from=src or None,
                phone_to=dst or None,
                recording_uri=row.get("recording_uri") or None,
                consent_flag=True,
                disposition=row.get("origCause_value") or "ANSWERED",
            )
        )
    return refs


_EXT_RE = __import__("re").compile(r"^[0-9]{2,5}$")


def _looks_ext(number: str) -> bool:
    return bool(_EXT_RE.match(number)) and len(number) <= 5


def _epoch_to_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(float(raw)), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return None


class CiscoUCMConnector:
    id = "cisco_ucm"

    def __init__(self, cdr_dir: str | Path, config: dict[str, Any] | None = None) -> None:
        self.cdr_dir = Path(cdr_dir)
        self.config = config or {}

    def verify(self) -> dict[str, Any]:
        return {"ok": self.cdr_dir.is_dir(), "cdr_dir": str(self.cdr_dir)}

    def discover_local(self, since: datetime, limit: int = 100) -> list[CallRef]:
        """Dev/фикстуры: чтение cdr_flat_*.csv из локального каталога."""
        refs: list[CallRef] = []
        for f in sorted(self.cdr_dir.glob("cdr_flat_*.csv")):
            refs.extend(parse_cdr_csv(f.read_text(encoding="utf-8", errors="replace"), since))
            if len(refs) >= limit:
                break
        return refs[:limit]

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        raise ConnectorError(
            "SFTP-режим Cisco коннектора подключается в M2 live-контуре "
            "(креды заказчика); локальный режим — discover_local"
        )

    def download(self, ref: CallRef) -> bytes:
        if ref.recording_uri:
            p = self.cdr_dir / ref.recording_uri
            if p.is_file():
                return p.read_bytes()
        raise ConnectorError("запись Cisco недоступна: не задан recording_uri или файл отсутствует")
