"""Системные таблицы: orgs, коннекторы, рубрики, словарь, модели, инсайты, аудит — doc 03 §2, §6."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from polylog.models.base import Base, CreatedMixin, PkMixin, utcnow


class Org(Base, PkMixin, CreatedMixin):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class User(Base, PkMixin, CreatedMixin):
    __tablename__ = "users"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(16), default="agent")  # admin|supervisor|analyst|agent|dpo
    display_name: Mapped[str | None] = mapped_column(String(255))
    agent_ext_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class Connector(Base, PkMixin, CreatedMixin):
    __tablename__ = "connectors"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # freepbx|bitrix24|amocrm|s3watch|http|devstand
    display_name: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # секреты коннектора — отдельное шифрованное поле в проде (doc 04 §6)
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Rubric(Base, PkMixin, CreatedMixin):
    __tablename__ = "rubrics"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # doc 02 §4.1
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class LexiconEntry(Base, PkMixin, CreatedMixin):
    __tablename__ = "lexicon_entries"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    phonetic_key: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(64))
    case_sensitive: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)


class ModelRegistry(Base, PkMixin, CreatedMixin):
    __tablename__ = "models_registry"

    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # asr|embed|classifier|nli|risk
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    license: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str | None] = mapped_column(String(128))
    dim: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # shadow|canary|active|retired


class Label(Base, PkMixin, CreatedMixin):
    __tablename__ = "labels"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    used_in_dataset: Mapped[str | None] = mapped_column(String(128))


class Insight(Base, PkMixin, CreatedMixin):
    __tablename__ = "insights"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # critical|warning|info
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new|ack|dismiss


class AuditLog(Base):
    """Append-only аудит (doc 04 §5). Без ПДн в details."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(48))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExportJob(Base, PkMixin, CreatedMixin):
    __tablename__ = "export_jobs"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # artifact|scenario|bundle
    filter_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    file_key: Mapped[str | None] = mapped_column(String(512))


class DatasetManifest(Base, PkMixin, CreatedMixin):
    """Манифест сплита датасета/эталона (doc 06 §4): hash, состав, лицензия, атрибуция."""

    __tablename__ = "dataset_manifests"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # kind: benchmark_asr | diarization_eval | dapt_train | labeling_pool
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)  # InfoBayAI/... , MaratDV/...
    license: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
