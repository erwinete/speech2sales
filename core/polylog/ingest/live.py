"""Live-режимы коннекторов (doc 02 §1.2, M2): SFTP-monitor записей и SQL-CDR
из внешних АТС. Универсальный вариант для «нестандартных» АТС, где нет
готового коннектора: CDR читается SQL-запросом, записи качаются по SFTP.

Транспорт SFTP — paramiko; в тестах подменяется фабрикой (DI), сеть не нужна.
SQL-источник — sync SQLAlchemy engine (любой DSN: postgres/mysql/mssql ODBC).

Конвенция имён записей (FreePBX-like): суффикс -in/-out определяет направление;
номер клиента — regex из конфига (named group `num`).
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from polylog.ingest.base import CallRef, ConnectorError

log = logging.getLogger("polylog.ingest.live")

_PHONE_RE = re.compile(r"^\+?\d{6,15}$")


@dataclass
class SftpConfig:
    host: str
    username: str
    password: str = ""
    port: int = 22
    key_path: str = ""
    remote_dir: str = "/var/spool/asterisk/monitor"
    # шаблон имён записей (fnmatch), например "q-*.wav"
    pattern: str = "*.wav"
    # regex по имени файла с named-группой num (номер клиента); optional
    name_regex: str = r"(?P<num>\+?\d{6,15})"
    key_filename: str = field(default="")


class SftpFileSource:
    """Чтение каталога записей по SFTP. connect_factory — DI-шов для тестов:
    возвращает объект с методами listdir_attr(path) и open(path)."""

    def __init__(self, config: SftpConfig, connect_factory: Callable[[], Any] | None = None) -> None:
        self.config = config
        self._factory = connect_factory or self._default_connect
        self._client: Any | None = None

    def _default_connect(self) -> Any:
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict[str, Any] = {
            "hostname": self.config.host,
            "port": self.config.port,
            "username": self.config.username,
        }
        if self.config.key_path:
            kwargs["key_filename"] = self.config.key_path
        elif self.config.password:
            kwargs["password"] = self.config.password
        client.connect(**kwargs)
        return client

    def _ensure(self) -> Any:
        if self._client is None:
            self._client = self._factory()
        return self._client

    def verify(self) -> dict[str, Any]:
        try:
            sftp = self._ensure().open_sftp()
            sftp.listdir(self.config.remote_dir)
            return {"ok": True, "host": self.config.host, "remote_dir": self.config.remote_dir}
        except Exception as e:  # noqa: BLE001 — для UI-мастера диагностика текстом
            return {"ok": False, "error": str(e)}

    def list_files(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """[{name, mtime, size}] по шаблону, новее since (если задана)."""
        client = self._ensure()
        sftp = client.open_sftp()
        out: list[dict[str, Any]] = []
        for entry in sftp.listdir_attr(self.config.remote_dir):
            name = entry.filename
            if not fnmatch.fnmatch(name, self.config.pattern):
                continue
            mtime = datetime.fromtimestamp(entry.st_mtime)
            if since is not None and mtime < since:
                continue
            out.append({"name": name, "mtime": mtime, "size": entry.st_size})
        out.sort(key=lambda x: x["mtime"])
        return out

    def read(self, name: str) -> bytes:
        client = self._ensure()
        sftp = client.open_sftp()
        with sftp.open(str(PurePosixPath(self.config.remote_dir) / name), "rb") as f:
            return f.read()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class SftpMonitorConnector:
    """Коннектор «SFTP-monitor»: записи качаются с АТС по SFTP; метаданные
    восстанавливаются из имени файла. id = sftp-monitor."""

    id = "sftp-monitor"

    def __init__(self, config: SftpConfig) -> None:
        self.source = SftpFileSource(config)
        self.config = config

    def verify(self) -> dict[str, Any]:
        return self.source.verify()

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        refs: list[CallRef] = []
        num_re = re.compile(self.config.name_regex) if self.config.name_regex else None
        for f in self.source.list_files(since)[:limit]:
            name = f["name"]
            direction = "inbound" if name.rstrip(".wav").endswith("-in") else "outbound"
            num = None
            if num_re is not None:
                m = num_re.search(name)
                if m:
                    candidate = m.group("num")
                    if _PHONE_RE.match(candidate):
                        num = candidate if candidate.startswith("+") else f"+{candidate}"
            refs.append(
                CallRef(
                    external_id=f"{self.id}:{name}",
                    started_at=f["mtime"],
                    direction=direction,
                    phone_from=num if direction == "inbound" else None,
                    phone_to=num if direction == "outbound" else None,
                    recording_uri=name,
                    consent_flag=True,
                )
            )
        return refs

    def download(self, ref: CallRef) -> bytes:
        if not ref.recording_uri:
            raise ConnectorError("у ref нет recording_uri")
        return self.source.read(ref.recording_uri)


class SqlCdrSource:
    """CDR из внешней SQL-БД (sync engine из DSN). Ожидаемая схема — стандартная
    asterisk cdr (uniqueid/calldate/src/dst/duration/billsec/disposition);
    имена колонок переопределяются конфигом."""

    DEFAULT_COLUMNS = {
        "uniqueid": "uniqueid",
        "calldate": "calldate",
        "src": "src",
        "dst": "dst",
        "duration": "duration",
        "billsec": "billsec",
        "disposition": "disposition",
    }

    def __init__(self, dsn: str, columns: dict[str, str] | None = None) -> None:
        self.dsn = dsn
        self.columns = {**self.DEFAULT_COLUMNS, **(columns or {})}
        self._engine: Any | None = None

    def engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine

            self._engine = create_engine(self.dsn, pool_pre_ping=True)
        return self._engine

    def verify(self) -> dict[str, Any]:
        from sqlalchemy import text

        try:
            with self.engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"ok": True, "dsn_set": bool(self.dsn)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        """Свежие записи CDR. calldate — локальное время АТС (naive): сравнение
        в SQL через >= since; уточнение под конкретную АТС — маппингом колонок
        в конфиге."""
        from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select

        cols = self.columns
        col_types: dict[str, Any] = {
            cols["calldate"]: DateTime(),
            cols["duration"]: Integer(),
            cols["billsec"]: Integer(),
        }
        table = Table(
            "cdr",
            MetaData(),
            *[Column(name, col_types.get(name, String(256))) for name in cols.values()],
        )
        refs: list[CallRef] = []
        with self.engine().connect() as conn:
            rows = conn.execute(
                select(table)
                .where(table.c[cols["calldate"]] >= since)
                .order_by(table.c[cols["calldate"]])
                .limit(limit)
            ).mappings().all()
        for r in rows:
            src = str(r.get(cols["src"]) or "")
            dst = str(r.get(cols["dst"]) or "")
            disposition = r.get(cols["disposition"])
            duration = r.get(cols["duration"])
            unique = str(r.get(cols["uniqueid"]) or f"{src}-{dst}-{r.get(cols['calldate'])}")
            # клиент — «внешний» номер (не короткий внутренний); второй конец —ext
            client = next(
                (n for n in (src, dst) if _PHONE_RE.match(n) and not (n.isdigit() and len(n) <= 6)),
                None,
            )
            ext = next((n for n in (src, dst) if n.isdigit() and len(n) <= 6), None)
            # входящий: внешний клиент в src звонил на внутренний (dst=ext);
            # иначе исходящий (внутренний в src звонит клиенту)
            direction = "inbound" if (ext and dst == ext) else "outbound"
            refs.append(
                CallRef(
                    external_id=f"sql-cdr:{unique}",
                    started_at=r.get(cols["calldate"]),
                    duration_sec=int(duration) if duration is not None else None,
                    direction=direction,
                    phone_from=src if client == src else ext,
                    phone_to=dst if client == dst else ext,
                    agent_ext=ext,
                    disposition=str(disposition) if disposition else None,
                    consent_flag=True,
                )
            )
        return refs


def sftp_config_from_env(prefix: str = "POLYLOG_SFTP_") -> SftpConfig:
    """Конфиг SFTP из переменных окружения: POLYLOG_SFTP_HOST/USER/PASSWORD/
    PORT/KEY_PATH/REMOTE_DIR/PATTERN/NAME_REGEX."""
    return SftpConfig(
        host=os.environ.get(f"{prefix}HOST", ""),
        username=os.environ.get(f"{prefix}USER", ""),
        password=os.environ.get(f"{prefix}PASSWORD", ""),
        port=int(os.environ.get(f"{prefix}PORT", "22")),
        key_path=os.environ.get(f"{prefix}KEY_PATH", ""),
        remote_dir=os.environ.get(f"{prefix}REMOTE_DIR", "/var/spool/asterisk/monitor"),
        pattern=os.environ.get(f"{prefix}PATTERN", "*.wav"),
        name_regex=os.environ.get(f"{prefix}NAME_REGEX", r"(?P<num>\+?\d{6,15})"),
    )
