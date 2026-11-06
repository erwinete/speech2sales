"""Роутер аутентификации (ТЗ §4.3-A): логин по email/паролю (PBKDF2),
текущий профиль. HMAC-токены — см. deps.encode_token/decode_token."""

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from polylog.api.deps import AuthDep, SessionDep, SettingsDep, encode_token
from polylog.models.system import AuditLog, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

PBKDF2_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return secrets.compare_digest(calc.hex(), digest)
    except (ValueError, AttributeError):
        return False


class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(body: LoginBody, session: SessionDep, settings: SettingsDep) -> dict:
    user = (
        (
            await session.execute(
                select(User).where(User.email == body.email.lower().strip(), User.is_active.is_(True))
            )
        )
        .scalars()
        .first()
    )
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "неверный email или пароль")
    user.last_login_at = datetime.now(UTC)
    session.add(
        AuditLog(
            org_id=user.org_id, actor_id=user.id, action="user_login",
            resource_type="user", resource_id=str(user.id), details=None,
        )
    )
    await session.commit()
    token = encode_token(user.id, user.org_id, user.role, settings.api_token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "org_id": str(user.org_id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "team_name": user.team_name,
            "agent_ext_ids": user.agent_ext_ids or [],
            "is_active": user.is_active,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat(),
        },
    }


@router.get("/me")
async def me(user: AuthDep, session: SessionDep) -> dict:
    """Профиль текущего пользователя; для service-ключа — синтетический admin."""
    if user.is_service or user.user_id is None:
        return {
            "id": None,
            "org_id": str(user.org_id),
            "email": user.email or "service@polylog",
            "display_name": "Service (API Key)",
            "role": "admin",
            "team_name": None,
            "agent_ext_ids": [],
            "is_active": True,
            "last_login_at": None,
            "created_at": datetime.now(UTC).isoformat(),
            "is_service": True,
        }
    u = await session.get(User, user.user_id)
    if u is None:
        raise HTTPException(401, "пользователь не найден")
    return {
        "id": str(u.id),
        "org_id": str(u.org_id),
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role,
        "team_name": u.team_name,
        "agent_ext_ids": u.agent_ext_ids or [],
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat(),
        "is_service": False,
    }
