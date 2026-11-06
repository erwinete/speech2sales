"""DTO коннекторов (ТЗ §4.3-B, §7.1)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConnectorCreate(BaseModel):
    kind: str
    display_name: str
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)
    poll_interval_min: int = 5
    status: str = "active"


class ConnectorUpdate(BaseModel):
    display_name: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    status: str | None = None
    poll_interval_min: int | None = None


class ConnectorOut(BaseModel):
    id: str
    kind: str
    display_name: str | None
    config: dict[str, Any]
    status: str
    poll_interval_min: int
    last_poll_at: datetime | None
    last_error: str | None
    calls_ingested_total: int
    webhook_url: str
    created_at: datetime


class SyncResultOut(BaseModel):
    discovered: int
    created: int
    skipped_duplicates: int
    errors: list[str]
