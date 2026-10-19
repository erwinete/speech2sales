"""Pydantic DTO API (валидация на границе, doc 04 §1)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CallOut(BaseModel):
    id: uuid.UUID
    external_id: str | None
    direction: str
    phone_from: str | None
    phone_to: str | None
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    started_at: datetime
    duration_sec: int | None
    state: str
    source: str
    consent_flag: bool | None
    avg_conf: float | None
    asr_backend_id: str | None
    thread_id: uuid.UUID | None
    chain_depth: int | None
    previous_call_id: uuid.UUID | None


class SegmentOut(BaseModel):
    idx: int
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    conf: float | None


class ObjectionOut(BaseModel):
    type: str
    span_text: str
    start_ms: int | None
    end_ms: int | None
    response_status: str | None
    confidence: float
    model_id: str


class ScoreOut(BaseModel):
    rubric_id: str
    rubric_version: int
    total: float
    items: list[dict[str, Any]] = Field(default_factory=list)
    scorer_version: str


class CallDetail(CallOut):
    stage_error: dict[str, Any] | None
    channels_map: dict[str, str] | None
    recording_key: str | None
    normalized_key: str | None
    segments: list[SegmentOut] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
    objections: list[ObjectionOut] = Field(default_factory=list)
    scores: list[ScoreOut] = Field(default_factory=list)


class CallList(BaseModel):
    total: int
    items: list[CallOut]


class UploadResult(BaseModel):
    call: CallOut
    created: bool
    message: str
