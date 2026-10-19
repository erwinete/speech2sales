"""FreePBX/Asterisk коннектор: CDR (SQL) + файлы monitor (doc 02 §1.2, doc 09).

CDR-таблица — стандартная asterisk `cdr` (пишется cdr_pg_csv в dev-стенде).
Поле recordingfile — FreePBX-расширение: относительный путь в monitor-каталоге.
Направление: по суффиксу имени записи `-in`/`-out` (конвенция FreePBX q-...-in.wav).
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.ingest.base import CallRef, ConnectorError

_PHONE_RE = re.compile(r"^\+?\d{6,15}$")

# Подмножество стандартной таблицы cdr (Asterisk), которое читает коннектор.
# recordingfile — FreePBX-расширение (относительный путь записи в monitor-каталоге).
_CDR_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("uniqueid", String(64)),
    ("calldate", DateTime(timezone=False)),
    ("src", String(64)),
    ("dst", String(64)),
    ("duration", Integer),
    ("billsec", Integer),
    ("disposition", String(32)),
    ("recordingfile", String(512)),
)

_CDR_TABLE = Table("cdr", MetaData(), *[Column(n, t) for n, t in _CDR_COLUMNS])


def _cdr_table() -> Table:
    return _CDR_TABLE


class FreePBXConnector:
    id = "freepbx"

    def __init__(self, monitor_dir: str | Path) -> None:
        self.monitor_dir = Path(monitor_dir)

    def verify(self) -> dict[str, Any]:
        return {
            "ok": self.monitor_dir.is_dir(),
            "monitor_dir": str(self.monitor_dir),
            "hint": "каталог monitor должен существовать и быть доступен на чтение",
        }

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        raise ConnectorError(
            "discover для FreePBX выполняется асинхронно через БД: "
            "используйте freepbx.discover_db(session, since)"
        )

    async def discover_db(self, session: AsyncSession, since: datetime, limit: int = 100) -> list[CallRef]:
        table = _cdr_table()
        # calldate в CDR — naive (локальное время АТС); сравниваем naive-UTC
        since_naive = since.astimezone(UTC).replace(tzinfo=None)
        rows = (
            (
                await session.execute(
                    select(table)
                    .where(table.c.calldate >= since_naive)
                    .order_by(table.c.calldate)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
        refs: list[CallRef] = []
        for r in rows:
            recording = r.get("recordingfile")
            if not recording:
                continue  # без записи анализировать нечего
            refs.append(self._row_to_ref(r))
        return refs

    def download(self, ref: CallRef) -> bytes:
        if not ref.recording_uri:
            raise ConnectorError(f"у звонка {ref.external_id} нет файла записи")
        path = self._resolve_recording(ref.recording_uri)
        return path.read_bytes()

    def download_sidecar(self, ref: CallRef) -> bytes | None:
        """Sidecar-транскрипт (`<имя>.transcript.json` рядом с записью), если есть —
        механизм доставки псевдотранскриптов/эталона (doc 09 §3, doc 06 §6)."""
        if not ref.recording_uri:
            return None
        path = self._resolve_recording(ref.recording_uri)
        sidecar = path.with_name(path.stem + ".transcript.json")
        return sidecar.read_bytes() if sidecar.is_file() else None

    def _resolve_recording(self, recording_uri: str) -> Path:
        path = self.monitor_dir / recording_uri
        if not path.is_file():
            # CDR хранит относительный путь; FreePBX часто кладёт в день-подкаталоги
            matches = list(self.monitor_dir.rglob(Path(recording_uri).name))
            if not matches:
                raise ConnectorError(f"файл записи не найден: {path}")
            path = matches[0]
        return path

    def _row_to_ref(self, r: Any) -> CallRef:
        recording = str(r["recordingfile"])
        direction = "inbound" if recording.rstrip(".wav").endswith("-in") else "outbound"
        src = (r.get("src") or "").strip() or None
        dst = (r.get("dst") or "").strip() or None
        # внутренние номера агентов — короткие; телефон клиента — длинный
        def is_phone(v: str | None) -> bool:
            return bool(v and _PHONE_RE.match(v) and len(v.lstrip("+")) >= 10)

        if direction == "inbound":
            phone_from, phone_to = src if is_phone(src) else None, dst
        else:
            phone_from, phone_to = src, dst if is_phone(dst) else None

        duration = int(r.get("duration") or 0)
        calldate: datetime = r["calldate"]
        if calldate.tzinfo is None:
            calldate = calldate.replace(tzinfo=UTC)

        return CallRef(
            external_id=str(r["uniqueid"]),
            started_at=calldate,
            duration_sec=duration or None,
            direction=direction,
            phone_from=phone_from,
            phone_to=phone_to,
            recording_uri=recording,
            channels_hint={"0": "agent", "1": "client"},
            consent_flag=True,
            disposition=r.get("disposition"),
        )


def make_insert_cdr_stmt(row: dict[str, Any]) -> Any:
    """Хелпер dev-стенда: statement вставки CDR-строки (использует injector)."""
    from sqlalchemy import insert

    return insert(_CDR_TABLE).values(**row)


def default_since() -> datetime:
    return datetime.now(UTC) - timedelta(days=365)
