"""Контракт коннекторов телефонии/CRM (doc 02 §1.1).

Коннектор потребляет артефакты АТС/CRM: CDR + файлы записей + метаданные.
Сигналинг не нужен — на этом построен dev-стенд (doc 09 §2).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ConnectorError(RuntimeError):
    pass


@dataclass
class CallRef:
    """Ссылка на звонок, обнаруженный в источнике."""

    external_id: str
    started_at: datetime
    duration_sec: int | None = None
    direction: str = "outbound"
    phone_from: str | None = None
    phone_to: str | None = None
    agent_ext: str | None = None
    recording_uri: str | None = None  # путь/ключ внутри коннектора
    channels_hint: dict[str, str] | None = None
    consent_flag: bool | None = None
    disposition: str | None = None  # ANSWERED|NO ANSWER|...
    crm_refs: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallMeta:
    """Обогащённые метаданные (doc 02 §1.1 metadata())."""

    ref: CallRef
    extra: dict[str, Any] = field(default_factory=dict)


class TelephonyConnector(Protocol):
    id: str

    def discover(self, since: datetime, limit: int = 100) -> list[CallRef]:
        """Новые звонки-кандидаты. Идемпотентность обеспечивает БД
        (unique org+connector+external_id) — коннектор может вернуть дубли."""
        ...

    def download(self, ref: CallRef) -> bytes:
        """Содержимое файла записи."""
        ...

    def verify(self) -> dict[str, Any]:
        """Проверка конфигурации/доступности для UI-мастера."""
        ...
