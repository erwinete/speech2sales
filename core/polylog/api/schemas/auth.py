"""DTO аутентификации и пользователей (ТЗ §4.3-A)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # EmailStr отвергает .local (reserved) — валидация простая, домен локальный
    email: str = Field(min_length=3, max_length=255)
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    team_name: str | None = None
    agent_ext_ids: list[str] = Field(default_factory=list)
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime
    calls_count: int | None = None
    avg_score: float | None = None
    has_voiceprint: bool | None = None
    voiceprint_samples: int | None = None


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str
    password: str = Field(min_length=6)
    role: Literal["admin", "supervisor", "analyst", "agent", "dpo"] = "agent"
    team_name: str | None = None
    agent_ext_ids: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: Literal["admin", "supervisor", "analyst", "agent", "dpo"] | None = None
    team_name: str | None = None
    agent_ext_ids: list[str] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)


TokenResponse.model_rebuild()
