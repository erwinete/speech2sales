"""Репроцесс конкретных звонков: python reprocess_ids.py <uuid> [uuid...]
Запуск из корня (читает .env); TMP/TEMP выставить на F: перед запуском."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))


from polylog.config import get_settings
from polylog.db import make_engine, make_sessionmaker
from polylog.models.calls import Call
from polylog.pipeline import process_call
from polylog.storage import make_storage


async def main() -> None:
    ids = [x.strip() for x in sys.argv[1:] if x.strip()]
    if not ids:
        print("usage: reprocess_ids.py <call_uuid> ...")
        return
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    storage = make_storage(settings)
    for n, raw in enumerate(ids, 1):
        from uuid import UUID

        call_id = UUID(raw)
        t0 = time.time()
        async with sm() as session:
            call = await session.get(Call, call_id)
            call.state = "failed"
            call.stage_error = None
            await session.commit()
        async with sm() as session:
            call = await process_call(session, call_id, settings, storage)
            await session.commit()  # без commit стадии откатываются при close
        print(f"[{n}/{len(ids)}] {raw} → {call.state} ({call.asr_backend_id}) за {time.time() - t0:.0f} c", flush=True)
    await engine.dispose()


asyncio.run(main())
