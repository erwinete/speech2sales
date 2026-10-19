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
