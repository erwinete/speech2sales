#!/usr/bin/env python3
"""S2-прогон dev-стенда: CDR из Postgres (инжектор) → коннектор → пайплайн → done.

Запуск (после `docker compose --profile devstand run --rm injector`):
    set POLYLOG_DATABASE_URL=postgresql+asyncpg://polylog:polylog@localhost:5432/polylog
    python tools/devstand/run_ingest.py [--backend stub|gigaam-v3-e2e-rnnt] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="stub")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--monitor-dir", default=str(ROOT / "data" / "monitor"))
    args = ap.parse_args()

    import os

    db_url = os.environ.get(
        "POLYLOG_DATABASE_URL", "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"
    )
    from polylog.config import Settings
    from polylog.db import init_db, make_engine, make_sessionmaker
    from polylog.graph.service import get_default_org
    from polylog.ingest.freepbx import FreePBXConnector
    from polylog.ingest.service import create_call_from_ref, get_or_create_connector
    from polylog.models.calls import Call
    from polylog.models.enums import CallState
    from polylog.pipeline import process_call
    from polylog.storage import LocalStorage

    settings = Settings(
        database_url=db_url,
        storage_dir=str(ROOT / "data" / "stand-storage"),
        tmp_dir=str(ROOT / "data" / "tmp"),
        api_token="stand",
        asr_backend=args.backend,
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = make_engine(db_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    storage = LocalStorage(settings.storage_dir)
    connector = FreePBXConnector(monitor_dir=args.monitor_dir)

    done = failed = created = 0
    async with sm() as session:
        org = await get_default_org(session)
        conn_row = await get_or_create_connector(session, org.id, "devstand", {})
        since = datetime.now(UTC) - timedelta(days=30)
        refs = await connector.discover_db(session, since, limit=args.limit)
        print(f"CDR найдено: {len(refs)}")
        for i, ref in enumerate(refs):
            audio = connector.download(ref)
            sidecar = connector.download_sidecar(ref) if hasattr(connector, "download_sidecar") else None
            call = await create_call_from_ref(
                session, org, conn_row, ref, storage, audio=audio, source="devstand", sidecar=sidecar
            )
            if call is None:
                continue  # уже ингестирован (идемпотентность)
            created += 1
            try:
                call = await process_call(session, call.id, settings, storage)
                await session.commit()
                if CallState(call.state) is CallState.done:
                    done += 1
                else:
                    failed += 1
            except Exception as e:  # noqa: BLE001
                await session.rollback()
                failed += 1
                print(f"  ! {ref.external_id}: {e}")
            if (i + 1) % 10 == 0:
                print(f"  … обработано {i + 1}/{len(refs)}")
    await engine.dispose()

    print(f"итог стенда: новых={created}, done={done}, failed={failed}")
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
