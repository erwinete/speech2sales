"""FreePBX-коннектор: discover из CDR, направление по имени записи, дедупликация ингеста."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import wav_bytes
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, insert
from sqlalchemy.ext.asyncio import create_async_engine

from polylog.config import Settings
from polylog.db import init_db, make_sessionmaker
from polylog.graph.service import get_default_org
from polylog.ingest.freepbx import FreePBXConnector
from polylog.ingest.service import create_call_from_ref, get_or_create_connector
from polylog.storage import LocalStorage


@pytest.fixture
def connector(tmp_path: Path) -> FreePBXConnector:
    monitor = tmp_path / "monitor"
    monitor.mkdir()
    (monitor / "q-101-777-out.wav").write_bytes(wav_bytes(2.0))
    (monitor / "q-102-888-in.wav").write_bytes(wav_bytes(2.0))
    return FreePBXConnector(monitor_dir=monitor)


@pytest.fixture
async def db(tmp_path: Path, settings: Settings):
    engine = create_async_engine(settings.database_url)
    await init_db(engine)
    md = MetaData()
    cdr_table = Table(
        "cdr", md,
        Column("uniqueid", String(64), primary_key=True),
        Column("calldate", DateTime),
        Column("src", String(64)),
        Column("dst", String(64)),
        Column("duration", Integer),
        Column("billsec", Integer),
        Column("disposition", String(32)),
        Column("recordingfile", String(512)),
    )
    sm = make_sessionmaker(engine)
    async with sm() as session:
        async with engine.begin() as conn:
            await conn.run_sync(md.create_all)
        await session.execute(
            insert(cdr_table).values([
                {
                    "uniqueid": "1001", "calldate": datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                    "src": "101", "dst": "+79001112233", "duration": 120, "billsec": 100,
                    "disposition": "ANSWERED", "recordingfile": "q-101-777-out.wav",
                },
                {
                    "uniqueid": "1002", "calldate": datetime(2026, 10, 1, 13, 0, tzinfo=UTC),
                    "src": "+74959998877", "dst": "102", "duration": 60, "billsec": 50,
                    "disposition": "ANSWERED", "recordingfile": "q-102-888-in.wav",
                },
            ])
        )
        await session.commit()
        yield session, md
    await engine.dispose()


async def test_discover_maps_direction_and_phones(db, connector: FreePBXConnector):
    session, _ = db
    since = datetime(2026, 9, 1, tzinfo=UTC)
    refs = await connector.discover_db(session, since)
    assert len(refs) == 2
    by_id = {r.external_id: r for r in refs}

    out = by_id["1001"]
    assert out.direction == "outbound"
    assert out.phone_from == "101"  # внутренний номер агента
    assert out.phone_to == "+79001112233"  # клиент — назначение исходящего
    assert out.channels_hint == {"0": "agent", "1": "client"}

    inc = by_id["1002"]
    assert inc.direction == "inbound"
    assert inc.phone_from == "+74959998877"


async def test_download_reads_monitor_file(db, connector: FreePBXConnector):
    session, _ = db
    refs = await connector.discover_db(session, datetime(2026, 9, 1, tzinfo=UTC))
    data = connector.download(refs[0])
    assert data[:4] == b"RIFF"


async def test_ingest_dedupes_by_external_id(db, connector: FreePBXConnector, tmp_path: Path):
    session, _ = db
    org = await get_default_org(session)
    conn_row = await get_or_create_connector(session, org.id, "freepbx", {"monitor_dir": str(tmp_path)})
    since = datetime(2026, 9, 1, tzinfo=UTC)
    refs = await connector.discover_db(session, since)

    storage = LocalStorage(tmp_path / "storage")
    first = await create_call_from_ref(session, org, conn_row, refs[0], storage,
                                       audio=wav_bytes(2.0), source="devstand")
    assert first is not None and first.state == "discovered"
    dup = await create_call_from_ref(session, org, conn_row, refs[0], storage,
                                     audio=wav_bytes(2.0), source="devstand")
    assert dup is None

    # второй звонок того же клиента (out) цепляется в цепочку контакта
    second = await create_call_from_ref(session, org, conn_row, refs[1], storage,
                                        audio=wav_bytes(2.0), source="devstand")
    assert second is not None
    await session.commit()
    await session.refresh(first)
    await session.refresh(second)
    assert first.chain_depth == 0 and first.thread_id == first.id
    # 1001 — outbound на +79001112233; 1002 — inbound от +74959998877 — разные контакты
    assert first.contact_id != second.contact_id
    assert first.chain_depth == 0 and second.chain_depth == 0
