#!/usr/bin/env python3
"""E2E-проверка очереди: звонок → discovered → enqueue → воркер → done.

Предусловия: procrastinate-схема применена (apply_queue_schema.py), воркер запущен.
Запуск: python queue_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "core"))

DB = os.environ.get("POLYLOG_DATABASE_URL", "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog")


async def pick_call() -> uuid.UUID:
    from sqlalchemy import select, update

    from polylog.models.calls import Call

    from polylog.config import Settings
    from polylog.db import make_engine, make_sessionmaker
    from polylog.storage import LocalStorage

    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    settings = Settings(
        database_url=DB, storage_dir=str(root / "data" / "stand-storage"),
        tmp_dir=str(root / "data" / "tmp"), _env_file=None,  # type: ignore[call-arg]
    )
    storage = LocalStorage(settings.storage_dir)
    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    async with sm() as s:
        rows = (
            await s.execute(
                select(Call)
                .where(Call.recording_key.is_not(None), Call.state == "done")
                .order_by(Call.started_at.desc())
                .limit(30)
            )
        ).scalars().all()
        call = next((c for c in rows if c.recording_key and storage.exists(c.recording_key)), None)
        if call is None:
            raise SystemExit("нет звонка с живой записью — перезапустите run_ingest.py")
        call_id = call.id
        await s.execute(update(Call).where(Call.id == call_id).values(state="discovered"))
        await s.commit()
    await engine.dispose()
    return call_id


async def wait_state(call_id: uuid.UUID, want: str, timeout_s: float = 90.0) -> str:
    from sqlalchemy import select

    from polylog.models.calls import Call

    from polylog.db import make_engine, make_sessionmaker

    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    deadline = time.time() + timeout_s
    state = "?"
    async with sm() as s:
        while time.time() < deadline:
            s.expire_all()  # перечитывать из БД, а не из identity map
            call = await s.get(Call, call_id)
            state = call.state
            if state == want:
                break
            await asyncio.sleep(2)
    await engine.dispose()
    return state


def main() -> int:
    call_id = asyncio.run(pick_call())
    print(f"звонок {call_id} сброшен в discovered")

    os.environ.setdefault("POLYLOG_DATABASE_URL", DB)
    from polylog.queue import enqueue_process_call

    if not enqueue_process_call(call_id):
        print("enqueue не удался (воркер/очередь недоступны)", file=sys.stderr)
        return 2
    print("задача поставлена в очередь, жду воркер…")

    state = asyncio.run(wait_state(call_id, "done", 90))
    print(f"итог: state={state}")
    return 0 if state == "done" else 3


if __name__ == "__main__":
    sys.exit(main())
