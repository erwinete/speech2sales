"""Сервис графа: нормализация номеров, резолюция контакта, сборка цепочки звонков
(doc 02 §7, doc 03 §4.1, ADR-16)."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.models.calls import Call
from polylog.models.graph import Contact, EntityLink, PhoneNumber
from polylog.models.system import Org

_PHONE_DIGITS = re.compile(r"\D+")


def normalize_phone(raw: str | None) -> str | None:
    """→ E.164 (+7XXXXXXXXXX для RU-форматов). None для внутренних/битых номеров."""
    if not raw:
        return None
    digits = _PHONE_DIGITS.sub("", raw)
    if not digits:
        return None
    if raw.lstrip().startswith("+"):
        return f"+{digits}" if 6 <= len(digits) <= 15 else None
    if len(digits) == 11 and digits.startswith("8"):
        return f"+7{digits[1:]}"
    if len(digits) == 10:
        return f"+7{digits}"
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    if 6 <= len(digits) <= 15:
        return f"+{digits}"  # без страны — оставляем как есть с плюсом
    return None  # короткие внутренние номера — не телефон клиента


async def get_default_org(session: AsyncSession, name: str = "default") -> Org:
    org = (await session.execute(select(Org).where(Org.name == name))).scalar_one_or_none()
    if org is None:
        org = Org(name=name)
        session.add(org)
        await session.flush()
    return org


async def resolve_contact(
    session: AsyncSession, org_id: uuid.UUID, phone_raw: str | None
) -> Contact | None:
    """Номер → контакт по графу (entity_links has_phone), иначе — создание
    contact + phone_number + связь с source=phone_match, confidence=1.0 (doc 03 §4)."""
    e164 = normalize_phone(phone_raw)
    if not e164:
        return None

    phone = (
        await session.execute(
            select(PhoneNumber).where(PhoneNumber.org_id == org_id, PhoneNumber.e164 == e164)
        )
    ).scalar_one_or_none()

    if phone is None:
        phone = PhoneNumber(org_id=org_id, e164=e164)
        session.add(phone)
        await session.flush()
        contact = Contact(org_id=org_id)
        session.add(contact)
        await session.flush()
        session.add(
            EntityLink(
                org_id=org_id,
                src_type="contact",
                src_id=str(contact.id),
                dst_type="phone_number",
                dst_id=str(phone.id),
                rel="has_phone",
                source="phone_match",
                confidence=1.0,
            )
        )
        return contact

    # существующий номер → контакт по связи (первая с максимальной уверенностью)
    link = (
        await session.execute(
            select(EntityLink)
            .where(
                EntityLink.org_id == org_id,
                EntityLink.src_type == "contact",
                EntityLink.dst_type == "phone_number",
                EntityLink.dst_id == str(phone.id),
                EntityLink.rel == "has_phone",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if link is not None:
        contact = await session.get(Contact, uuid.UUID(link.src_id))
        if contact is not None:
            return contact

    contact = Contact(org_id=org_id)
    session.add(contact)
    await session.flush()
    session.add(
        EntityLink(
            org_id=org_id,
            src_type="contact",
            src_id=str(contact.id),
            dst_type="phone_number",
            dst_id=str(phone.id),
            rel="has_phone",
            source="phone_match",
            confidence=1.0,
        )
    )
    return contact


async def rebuild_chain(session: AsyncSession, org_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    """Пересборка цепочки previous_call_id / thread_id / chain_depth по времени
    (doc 03 §4.1). Транзакционна в рамках внешней сессии; вызывается после
    вставки/перепривязки звонков."""
    calls = (
        (
            await session.execute(
                select(Call)
                .where(Call.org_id == org_id, Call.contact_id == contact_id)
                .order_by(Call.started_at, Call.id)
            )
        )
        .scalars()
        .all()
    )
    thread_root: uuid.UUID | None = None
    prev: Call | None = None
    for depth, call in enumerate(calls):
        call.previous_call_id = prev.id if prev is not None else None
        call.thread_id = thread_root if thread_root is not None else call.id
        if depth == 0:
            thread_root = call.id
        call.chain_depth = depth
        prev = call
