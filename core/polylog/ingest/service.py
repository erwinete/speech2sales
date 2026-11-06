"""Сервис ингеста: создание звонка из CallRef + связка с графом (doc 02 §1, doc 01 §5.2)."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.graph.service import rebuild_chain, resolve_contact
from polylog.ingest.base import CallRef
from polylog.models.calls import Call
from polylog.models.enums import CallState, Direction
from polylog.models.system import Connector, Org
from polylog.storage import Storage

log = logging.getLogger("polylog.ingest")


async def get_or_create_connector(
    session: AsyncSession, org_id: uuid.UUID, kind: str, config: dict | None = None
) -> Connector:
    conn = (
        await session.execute(
            select(Connector).where(Connector.org_id == org_id, Connector.kind == kind)
        )
    ).scalar_one_or_none()
    if conn is None:
        conn = Connector(org_id=org_id, kind=kind, config=config or {})
        session.add(conn)
        await session.flush()
    return conn


def _agent_ext_of(ref: CallRef) -> str | None:
    """Внутренний номер менеджера: из ref.agent_ext, иначе короткий числовой
    (<=6 цифр) конец звонка по направлению (outbound — phone_from,
    inbound — phone_to)."""
    if ref.agent_ext:
        return ref.agent_ext
    candidate = ref.phone_from if ref.direction == "outbound" else ref.phone_to
    if candidate and candidate.isdigit() and len(candidate) <= 6:
        return candidate
    return None


async def resolve_agent_user(
    session: AsyncSession, org_id: uuid.UUID, agent_ext: str | None
):
    """Менеджер организации по внутреннему номеру (User.agent_ext_ids)."""
    if not agent_ext:
        return None
    from polylog.models.system import User

    users = (
        (
            await session.execute(
                select(User).where(User.org_id == org_id, User.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for u in users:
        if agent_ext in (u.agent_ext_ids or []):
            return u
    return None


async def create_call_from_ref(
    session: AsyncSession,
    org: Org,
    connector: Connector | None,
    ref: CallRef,
    storage: Storage,
    audio: bytes | None = None,
    source: str = "connector",
    sidecar: bytes | None = None,
) -> Call | None:
    """Идемпотентно создаёт Call из CallRef. None — дубликат (external_id уже есть).

    Аудио сохраняется в хранилище с ключом по sha256-дублю контента
    (репроцессинг не дублирует файлы, doc 01 §5.1). sidecar — транскрипт-эталон
    (`.transcript.json`), сохраняется рядом с аудио (stub-ASR подхватывает)."""
    stmt = select(Call).where(
        Call.org_id == org.id,
        Call.external_id == ref.external_id,
    )
    if connector is not None:
        stmt = stmt.where(Call.connector_id == connector.id)
    else:
        stmt = stmt.where(Call.connector_id.is_(None))
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return None

    recording_key: str | None = None
    if audio is not None and ref.recording_uri:
        import hashlib
        from pathlib import Path

        digest = hashlib.sha256(audio).hexdigest()[:16]
        suffix = Path(ref.recording_uri).suffix or ".wav"
        recording_key = f"calls/{org.id}/{digest}{suffix}"
        if not storage.exists(recording_key):
            storage.save(recording_key, audio)
        if sidecar is not None:
            sidecar_key = f"{recording_key}.transcript.json"
            if not storage.exists(sidecar_key):
                storage.save(sidecar_key, sidecar)

    call = Call(
        org_id=org.id,
        connector_id=connector.id if connector else None,
        external_id=ref.external_id,
        direction=ref.direction if ref.direction in Direction._value2member_map_ else "outbound",
        phone_from=ref.phone_from,
        phone_to=ref.phone_to,
        started_at=ref.started_at,
        duration_sec=ref.duration_sec,
        recording_key=recording_key,
        channels_map=ref.channels_hint,
        consent_flag=ref.consent_flag,
        state=CallState.discovered.value,
        source=source,
    )
    session.add(call)
    await session.flush()

    # клиент: inbound — phone_from, outbound — phone_to (doc 02 §1.2)
    client_phone = ref.phone_from if ref.direction == "inbound" else ref.phone_to
    contact = await resolve_contact(session, org.id, client_phone)
    if contact is not None:
        call.contact_id = contact.id
        call.company_id = contact.company_id
        await rebuild_chain(session, org.id, contact.id)

    # менеджер: Call.agent_user_id по внутреннему номеру (doc 02 §1.2, RBAC)
    agent_user = await resolve_agent_user(session, org.id, _agent_ext_of(ref))
    if agent_user is not None:
        call.agent_user_id = agent_user.id

    log.info("создан звонок %s (%s, %s)", call.id, ref.external_id, call.state)
    return call


async def next_discovered_calls(session: AsyncSession, limit: int = 50) -> list[Call]:
    return list(
        (
            await session.execute(
                select(Call)
                .where(Call.state == CallState.discovered.value)
                .order_by(Call.started_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
