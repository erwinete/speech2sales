"""Зависимости FastAPI: настройки, сессия БД, аутентификация (doc 04 §1, §5)."""

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


def verify_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Skeleton-аутентификация: статический токен организации.
    Прод: OIDC/LDAP + RBAC row-level (doc 04 §5) — контракт зависимости сохранится."""
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing X-Api-Key"
        )


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[None, Depends(verify_api_key)]
