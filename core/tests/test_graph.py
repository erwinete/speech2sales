"""Граф: нормализация номеров, резолюция контакта, цепочка previous_call_id/thread_id."""

from datetime import UTC, datetime, timedelta

import pytest

from polylog.graph.service import (
    get_default_org,
    normalize_phone,
    rebuild_chain,
    resolve_contact,
)
from polylog.models.calls import Call


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+79001234567", "+79001234567"),
        ("8 (900) 123-45-67", "+79001234567"),
        ("9001234567", "+79001234567"),
        ("79001234567", "+79001234567"),
        ("101", None),  # внутренний номер
        ("", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


async def test_resolve_contact_creates_phone_and_link(session):
    org = await get_default_org(session)
    c1 = await resolve_contact(session, org.id, "+79001234567")
    c2 = await resolve_contact(session, org.id, "8 (900) 123-45-67")
    assert c1 is not None and c2 is not None
    assert c1.id == c2.id  # разные написания — один контакт


async def test_chain_rebuild(session):
    org = await get_default_org(session)
    contact = await resolve_contact(session, org.id, "+79001234567")
    base = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    calls = []
    for i in [2, 0, 1]:  # вставка в произвольном порядке
        call = Call(
            org_id=org.id, contact_id=contact.id, external_id=f"x{i}",
            direction="outbound", phone_to="+79001234567",
            started_at=base + timedelta(hours=i), state="discovered",
        )
        session.add(call)
        calls.append(call)
    await session.flush()
    await rebuild_chain(session, org.id, contact.id)
    await session.commit()
    for c in calls:
        await session.refresh(c)
    ordered = sorted(calls, key=lambda c: c.started_at)
    assert [c.chain_depth for c in ordered] == [0, 1, 2]
    assert ordered[0].previous_call_id is None
    assert ordered[1].previous_call_id == ordered[0].id
    assert all(c.thread_id == ordered[0].id for c in ordered)


async def test_chain_rebuild_after_relink(session):
    """Перепривязка звонка на другой контакт пересобирает обе цепочки."""
    org = await get_default_org(session)
    ca = await resolve_contact(session, org.id, "+79001112233")
    cb = await resolve_contact(session, org.id, "+79004445566")
    base = datetime(2026, 10, 1, tzinfo=UTC)
    a1 = Call(org_id=org.id, contact_id=ca.id, external_id="a1", direction="outbound",
              started_at=base, state="discovered")
    a2 = Call(org_id=org.id, contact_id=ca.id, external_id="a2", direction="outbound",
              started_at=base + timedelta(hours=1), state="discovered")
    session.add_all([a1, a2])
    await session.flush()
    await rebuild_chain(session, org.id, ca.id)

    # a2 уезжает на другой контакт с более ранним существующим звонком
    b1 = Call(org_id=org.id, contact_id=cb.id, external_id="b1", direction="outbound",
              started_at=base - timedelta(hours=1), state="discovered")
    session.add(b1)
    await session.flush()
    a2.contact_id = cb.id
    await rebuild_chain(session, org.id, ca.id)
    await rebuild_chain(session, org.id, cb.id)
    await session.commit()
    for c in (a1, a2, b1):
        await session.refresh(c)
    assert a1.chain_depth == 0 and a1.previous_call_id is None
    assert b1.chain_depth == 0 and b1.thread_id == b1.id
    assert a2.chain_depth == 1 and a2.previous_call_id == b1.id


async def test_isolated_orgs_same_phone(session):
    """Multi-org модель: одинаковый номер в разных org — разные контакты."""
    org_a = await get_default_org(session, "alpha")
    org_b = await get_default_org(session, "beta")
    ca = await resolve_contact(session, org_a.id, "+79001234567")
    cb = await resolve_contact(session, org_b.id, "+79001234567")
    assert ca.id != cb.id
    await session.commit()
