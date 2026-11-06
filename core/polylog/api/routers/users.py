"""Роутер пользователей и голосовых отпечатков (ТЗ §4.3-A)."""

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from polylog.api.deps import AdminDep, AdminOrSupervisorDep, SessionDep
from polylog.api.routers.auth import hash_password
from polylog.api.schemas import UserCreate, UserUpdate
from polylog.models.calls import Call, Score
from polylog.models.system import AuditLog, User

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _audit(session, org_id, actor, action: str, resource_id: str, details: dict | None = None) -> None:
    session.add(
        AuditLog(
            org_id=org_id,
            actor_id=actor.user_id if actor else None,
            action=action,
            resource_type="user",
            resource_id=resource_id,
            details=details,
        )
    )


async def _bind_calls(session, org_id, user: User) -> int:
    """Ретроспективная привязка звонков по внутренним номерам пользователя."""
    exts = user.agent_ext_ids or []
    if not exts:
        return 0
    rows = (
        (
            await session.execute(
                select(Call).where(
                    Call.org_id == org_id,
                    Call.agent_user_id.is_(None),
                    Call.phone_from.in_(exts) | Call.phone_to.in_(exts),
                )
            )
        )
        .scalars()
        .all()
    )
    for c in rows:
        c.agent_user_id = user.id
    return len(rows)


@router.get("")
async def list_users(
    session: SessionDep,
    user: AdminOrSupervisorDep,
    role: str | None = None,
    team: str | None = None,
    q: str | None = None,
    is_active: bool | None = None,
) -> dict:
    org = user.org_id
    conds = [User.org_id == org]
    if role:
        conds.append(User.role == role)
    if team:
        conds.append(User.team_name == team)
    if q:
        conds.append(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    if is_active is not None:
        conds.append(User.is_active.is_(is_active))
    users = ((await session.execute(select(User).where(*conds))).scalars().all())

    # агрегаты звонков одним запросом (GROUP BY agent_user_id)
    call_stats = {
        r[0]: r
        for r in (
            await session.execute(
                select(
                    Call.agent_user_id,
                    func.count(),
                    func.avg(Score.total),
                )
                .select_from(Call)
                .outerjoin(Score, Score.call_id == Call.id)
                .where(Call.org_id == org)
                .group_by(Call.agent_user_id)
            )
        ).all()
    }
    from polylog.models.graph import AgentVoice

    voices = {
        v.agent_key: v
        for v in (
            await session.execute(select(AgentVoice).where(AgentVoice.org_id == org))
        ).scalars().all()
    }

    items = []
    for u in users:
        stats = call_stats.get(u.id)
        vp = None
        for ext in u.agent_ext_ids or []:
            if ext in voices:
                vp = voices[ext]
                break
        items.append({
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
            "calls_count": int(stats[1]) if stats else 0,
            "avg_score": round(float(stats[2]), 1) if stats and stats[2] is not None else None,
            "has_voiceprint": vp is not None,
            "voiceprint_samples": vp.samples if vp else 0,
        })
    return {"items": items, "total": len(items)}


@router.post("")
async def create_user(body: UserCreate, session: SessionDep, actor: AdminDep) -> dict:
    exists = (
        await session.execute(select(User).where(User.email == body.email.lower().strip()))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "пользователь с таким email уже существует")
    user = User(
        org_id=actor.org_id,
        email=body.email.lower().strip(),
        display_name=body.display_name,
        role=body.role,
        team_name=body.team_name,
        agent_ext_ids=body.agent_ext_ids,
        password_hash=hash_password(body.password),
        is_active=True,
    )
    session.add(user)
    await session.flush()
    bound = await _bind_calls(session, actor.org_id, user)
    _audit(session, actor.org_id, actor, "user_create", str(user.id), {"email": user.email, "bound_calls": bound})
    await session.commit()
    return {"id": str(user.id), "email": user.email, "bound_calls": bound}


@router.patch("/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdate, session: SessionDep, actor: AdminDep) -> dict:
    user = await session.get(User, user_id)
    if user is None or user.org_id != actor.org_id:
        raise HTTPException(404, "пользователь не найден")
    changes: dict = {}
    if body.display_name is not None:
        user.display_name = body.display_name
        changes["display_name"] = body.display_name
    if body.role is not None:
        user.role = body.role
        changes["role"] = body.role
    if body.team_name is not None:
        user.team_name = body.team_name
    if body.agent_ext_ids is not None:
        user.agent_ext_ids = body.agent_ext_ids
        changes["agent_ext_ids"] = body.agent_ext_ids
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    bound = await _bind_calls(session, actor.org_id, user)
    _audit(session, actor.org_id, actor, "user_update", str(user.id), changes or None)
    await session.commit()
    return {"id": str(user.id), "bound_calls": bound}


@router.delete("/{user_id}")
async def deactivate_user(user_id: uuid.UUID, session: SessionDep, actor: AdminDep) -> dict:
    user = await session.get(User, user_id)
    if user is None or user.org_id != actor.org_id:
        raise HTTPException(404, "пользователь не найден")
    user.is_active = False
    rows = (
        (
            await session.execute(
                select(Call).where(Call.org_id == actor.org_id, Call.agent_user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    for c in rows:
        c.agent_user_id = None
    _audit(session, actor.org_id, actor, "user_deactivate", str(user.id))
    await session.commit()
    return {"id": str(user.id), "is_active": False, "unbound_calls": len(rows)}


@router.get("/voiceprints")
async def list_voiceprints(session: SessionDep, user: AdminOrSupervisorDep) -> dict:
    from polylog.models.graph import AgentVoice

    rows = (
        (
            await session.execute(select(AgentVoice).where(AgentVoice.org_id == user.org_id))
        )
        .scalars()
        .all()
    )
    users = (
        (
            await session.execute(select(User).where(User.org_id == user.org_id))
        )
        .scalars()
        .all()
    )
    by_ext: dict[str, dict] = {}
    for u in users:
        for ext in u.agent_ext_ids or []:
            by_ext[ext] = {"id": str(u.id), "display_name": u.display_name, "email": u.email}
    return {
        "items": [
            {
                "agent_key": v.agent_key,
                "samples": v.samples,
                "model_id": v.model_id,
                "created_at": v.created_at.isoformat(),
                "user": by_ext.get(v.agent_key),
            }
            for v in rows
        ]
    }


@router.delete("/voiceprints/{agent_key}")
async def delete_voiceprint(agent_key: str, session: SessionDep, actor: AdminDep) -> dict:
    from polylog.models.graph import AgentVoice

    row = (
        (
            await session.execute(
                select(AgentVoice).where(
                    AgentVoice.org_id == actor.org_id, AgentVoice.agent_key == agent_key
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, "отпечаток не найден")
    await session.delete(row)
    _audit(session, actor.org_id, actor, "voiceprint_reset", agent_key)
    await session.commit()
    return {"agent_key": agent_key, "deleted": True}
