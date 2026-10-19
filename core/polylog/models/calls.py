"""Звонки, транскрипты, находки, скоры, риск, PII — doc 03 §3."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from polylog.models.base import Base, CreatedMixin, PkMixin, utcnow


class Call(Base, PkMixin, CreatedMixin):
    __tablename__ = "calls"
    __table_args__ = (
        UniqueConstraint("org_id", "connector_id", "external_id",
                         name="uq_calls_external"),
        Index("ix_calls_org_started", "org_id", "started_at"),
        Index("ix_calls_org_state", "org_id", "state"),
        Index("ix_calls_thread", "thread_id"),
        Index("ix_calls_contact", "contact_id", "started_at"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    connector_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(16), default="outbound")
    phone_from: Mapped[str | None] = mapped_column(String(32))
    phone_to: Mapped[str | None] = mapped_column(String(32))
    agent_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_sec: Mapped[int | None] = mapped_column(Integer)

    recording_key: Mapped[str | None] = mapped_column(String(512))
    normalized_key: Mapped[str | None] = mapped_column(String(512))
    channels_map: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)

    consent_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload|devstand|connector

    state: Mapped[str] = mapped_column(String(32), default="discovered", nullable=False)
    stage_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    previous_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    chain_depth: Mapped[int | None] = mapped_column(Integer)

    language: Mapped[str] = mapped_column(String(8), default="ru")
    asr_backend_id: Mapped[str | None] = mapped_column(String(64))
    avg_conf: Mapped[float | None] = mapped_column(Float)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    segments: Mapped[list["CallSegment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan",
        order_by="CallSegment.idx", lazy="selectin",
    )
    metrics: Mapped["CallMetrics | None"] = relationship(
        back_populates="call", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )
    objections: Mapped[list["Objection"]] = relationship(
        back_populates="call", cascade="all, delete-orphan", lazy="selectin"
    )
    signals: Mapped[list["Signal"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
        primaryjoin="Call.id==Signal.call_id", viewonly=True,
    )
    violations: Mapped[list["Violation"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
        primaryjoin="Call.id==Violation.call_id", viewonly=True,
    )


class CallSegment(Base, PkMixin, CreatedMixin):
    __tablename__ = "call_segments"
    __table_args__ = (UniqueConstraint("call_id", "idx", name="uq_segments_idx"),)

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    words: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    conf: Mapped[float | None] = mapped_column(Float)
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    call: Mapped[Call] = relationship(back_populates="segments")


class CallMetrics(Base, PkMixin, CreatedMixin):
    __tablename__ = "call_metrics"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    call: Mapped[Call] = relationship(back_populates="metrics")


class Objection(Base, PkMixin, CreatedMixin):
    __tablename__ = "objections"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(64))
    span_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(16))
    response_status: Mapped[str | None] = mapped_column(String(24))
    response_span: Mapped[str | None] = mapped_column(Text)
    response_end_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False)

    call: Mapped[Call] = relationship(back_populates="objections")


class Signal(Base, PkMixin, CreatedMixin):
    __tablename__ = "signals"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    span_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)


class Violation(Base, PkMixin, CreatedMixin):
    __tablename__ = "violations"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    span_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)


class Score(Base, PkMixin, CreatedMixin):
    __tablename__ = "scores"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    rubric_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    scorer_version: Mapped[str] = mapped_column(String(64), nullable=False)


class RiskAssessment(Base, PkMixin, CreatedMixin):
    __tablename__ = "risk_assessments"

    call_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=True
    )
    deal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    prob_loss: Mapped[float | None] = mapped_column(Float)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=True)
    factors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    abstain_reason: Mapped[str | None] = mapped_column(String(255))


class PIIFinding(Base, PkMixin, CreatedMixin):
    __tablename__ = "pii_findings"

    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # masked|hashed|redacted|kept
    segment_idx: Mapped[int | None] = mapped_column(Integer)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    value_hash: Mapped[str | None] = mapped_column(String(128))
    detector: Mapped[str] = mapped_column(String(64), nullable=False)
