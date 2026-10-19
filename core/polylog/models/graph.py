"""Граф Customer 360: телефоны, контакты, компании, сделки, взаимодействия, рёбра — doc 03 §4."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from polylog.models.base import Base, CreatedMixin, PkMixin


class PhoneNumber(Base, PkMixin, CreatedMixin):
    __tablename__ = "phone_numbers"
    __table_args__ = (UniqueConstraint("org_id", "e164", name="uq_phones_e164"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    e164: Mapped[str] = mapped_column(String(24), nullable=False)
    ext: Mapped[str | None] = mapped_column(String(16))  # внутренний номер агента


class Contact(Base, PkMixin, CreatedMixin):
    __tablename__ = "contacts"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    crm_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    merged_into: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    calls_allowed: Mapped[bool] = mapped_column(Boolean, default=True)  # не ПДн-флаг; заглушка ролей


class Company(Base, PkMixin, CreatedMixin):
    __tablename__ = "companies"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    inn: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(64))  # domain-clf M8 (doc 08 §1)
    crm_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Deal(Base, PkMixin, CreatedMixin):
    __tablename__ = "deals"

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    crm_ref: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(16))  # open|won|lost|unknown
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Interaction(Base, PkMixin, CreatedMixin):
    __tablename__ = "interactions"
    __table_args__ = (Index("ix_interactions_contact_time", "contact_id", "occurred_at"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # call|email|chat|meeting|sms
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class AgentVoice(Base, PkMixin, CreatedMixin):
    """Голосовой отпечаток агента (voiceprint, DoD М3 §2.1): усреднённый
    эмбеддинг pyannote по его каналам в стерео-звонках. Ключ — внутренний
    номер АТС (прокси до модели «сотрудник» из CRM, M2). Вектора в JSON —
    агентов ≤200, косинус считается в Python (pgvector не нужен)."""

    __tablename__ = "agent_voices"
    __table_args__ = (UniqueConstraint("org_id", "agent_key", name="uq_agent_voice"),)

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_key: Mapped[str] = mapped_column(String(32), nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, default=1)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)


class EntityLink(Base, PkMixin, CreatedMixin):
    """Полиморфное ребро графа. Целостность концов — сервисный слой (doc 03 §4)."""

    __tablename__ = "entity_links"
    __table_args__ = (
        UniqueConstraint("src_type", "src_id", "dst_type", "dst_id", "rel", name="uq_links_edge"),
        Index("ix_links_src", "src_type", "src_id"),
        Index("ix_links_dst", "dst_type", "dst_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    src_type: Mapped[str] = mapped_column(String(32), nullable=False)
    src_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dst_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dst_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # rel: has_phone | belongs_to | placed_call | mentions | same_as | refs_deal
    rel: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # crm | phone_match | ner_match | manual
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # период владения связью: «переехавший» номер не тянет старые звонки
    # в аналитику нового владельца (ADR-16, doc 08 §3.2)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TextMention(Base, PkMixin, CreatedMixin):
    """NER-упоминание в транскрипте (Yargy/Natasha, M2) — подсказки для ручного слияния."""

    __tablename__ = "text_mentions"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    segment_idx: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # person|org|amount|date|phone|email
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
