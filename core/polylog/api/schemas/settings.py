"""DTO настроек: рубрики, словарь (ТЗ §4.3-E)."""

from typing import Any

from pydantic import BaseModel, Field


class RubricUpdate(BaseModel):
    name: str
    description: str | None = None
    spec: dict[str, Any]
    rescore_days: int | None = None


class LexiconEntryCreate(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)
    phonetic_key: str | None = None
    category: str | None = None
    case_sensitive: bool = False
    enabled: bool = True
