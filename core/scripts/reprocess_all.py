"""Репроцесс ВСЕХ звонков стенда: пересчёт метрик (сентимент), скоров, ролей
на актуальном коде. Запуск из КОРНЯ репо (чтобы прочитался .env):
  .venv\\Scripts\\python.exe core\\scripts\\reprocess_all.py
Идемпотентно: сегменты/скоры удаляются и создаются заново."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # core/ в path

from sqlalchemy import select

from polylog.config import get_settings
from polylog.db import make_engine, make_sessionmaker
from polylog.models.calls import Call
from polylog.pipeline import process_call
from polylog.storage import make_storage


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    storage = make_storage(settings)

    async with sm() as session:
        ids = (
            (await session.execute(select(Call.id).order_by(Call.started_at)))
            .scalars()
            .all()
        )
    print(f"звонков к репроцессу: {len(ids)}", flush=True)

    ok = failed = 0
    for n, call_id in enumerate(ids, 1):
        t0 = time.time()
        try:
            async with sm() as session:
                call = await session.get(Call, call_id)
                call.state = "failed"  # reprocess на done — no-op, сбрасываем
                call.stage_error = None
                await session.commit()
            async with sm() as session:
                call = await process_call(session, call_id, settings, storage)
                state, backend = call.state, call.asr_backend_id
                await session.commit()  # без commit стадии откатываются при close
            if state == "done":
                ok += 1
            else:
                failed += 1
            print(f"[{n}/{len(ids)}] {call_id} → {state} ({backend}) за {time.time() - t0:.0f} c", flush=True)
        except Exception as e:  # noqa: BLE001 — один звонок не останавливает обход
            failed += 1
            print(f"[{n}/{len(ids)}] {call_id} FAILED: {e}", flush=True)

    print(f"ИТОГ: ok={ok}, failed={failed}", flush=True)
    await engine.dispose()


asyncio.run(main())
