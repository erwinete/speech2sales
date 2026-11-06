"""Зависимости FastAPI: настройки, сессия БД, аутентификация и RBAC
(doc 04 §1, §5; ТЗ §4.2).

Два режима авторизации:
- `X-Api-Key` (service/legacy): виртуальный контекст role=admin — 151
  существующий тест проходят без изменений;
- `Authorization: Bearer <token>` (пользователи UI): HMAC-подпись
  {user_id, org_id, role}, секрет — settings.api_token (std-lib hmac).
"""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.config import Settings

ROLES = ("admin", "supervisor", "analyst", "agent", "dpo")
# матрица: role → множество допустимых ролей-читателей и т.п. (см. require_role)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


@dataclass
class CurrentUser:
    """Контекст авторизации запроса."""

    user_id: uuid.UUID | None
    org_id: uuid.UUID
    role: str
    email: str | None = None
    is_service: bool = False

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


def encode_token(user_id: uuid.UUID, org_id: uuid.UUID, role: str, secret: str) -> str:
    payload = {
        "uid": str(user_id),
        "oid": str(org_id),
        "role": role,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def decode_token(token: str, secret: str) -> dict:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError as e:
        raise HTTPException(401, "неверный формат токена") from e
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "неверная подпись токена")
    try:
        padded = body + "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, "повреждённый токен") from e


def _virtual_admin(request: Request) -> CurrentUser:
    org = request.app.state.default_org
    return CurrentUser(user_id=None, org_id=org.id, role="admin", email="service@polylog", is_service=True)


async def authenticate(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Единая точка авторизации: X-Api-Key (service) или Bearer (пользователь)."""
    if x_api_key:
        if secrets.compare_digest(x_api_key, settings.api_token):
            return _virtual_admin(request)
        raise HTTPException(401, "invalid X-Api-Key")

    if authorization and authorization.lower().startswith("bearer "):
        claims = decode_token(authorization[7:].strip(), settings.api_token)
        user_id = uuid.UUID(claims["uid"])
        sessionmaker = request.app.state.sessionmaker
        from polylog.models.system import User

        async with sessionmaker() as s:
            user = await s.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(401, "пользователь не найден или деактивирован")
        return CurrentUser(
            user_id=user.id, org_id=user.org_id, role=user.role, email=user.email
        )

    # ?api_key= — для <audio> плеера (не умеет заголовки)
    api_key = request.query_params.get("api_key")
    if api_key and secrets.compare_digest(api_key, settings.api_token):
        return _virtual_admin(request)

    raise HTTPException(401, "требуется авторизация: X-Api-Key или Bearer токен")


def require_role(*roles: str):
    """Фабрика зависимости: проверка роли текущего пользователя (RBAC)."""

    async def _checker(user: Annotated[CurrentUser, Depends(authenticate)]) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(403, f"недостаточно прав: требуется {'/'.join(roles)}")
        return user

    return _checker


# Часто используемые зависимости ролей
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[CurrentUser, Depends(authenticate)]
AdminDep = Annotated[CurrentUser, Depends(require_role("admin"))]
AdminOrSupervisorDep = Annotated[CurrentUser, Depends(require_role("admin", "supervisor"))]
