"""Перескоринг всех done-звонков стенда (после гуманизации объяснений)."""

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

ROOT = Path(__file__).resolve().parents[2]
DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"


async def main() -> None:
    from sqlalchemy import select, update

    from polylog.config import Settings
    from polylog.db import make_engine, make_sessionmaker
    from polylog.models.calls import Call
    from polylog.models.enums import CallState
    from polylog.pipeline import process_call
    from polylog.storage import LocalStorage

    settings = Settings(
        database_url=DB,
        storage_dir=str(ROOT / "data" / "stand-storage"),
        tmp_dir=str(ROOT / "data" / "tmp"),
        api_token="stand",
        asr_backend="stub",
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    storage = LocalStorage(settings.storage_dir)
    n = ok = 0
    async with sm() as s:
        calls = (
            (
                await s.execute(
                    select(Call).where(Call.state.in_(["done", "scored", "analyzed"]))
                )
            )
            .scalars()
            .all()
        )
        for call in calls:
            await s.execute(
                update(Call).where(Call.id == call.id).values(state=CallState.analyzed.value)
            )
            await s.commit()
            try:
                call = await process_call(s, call.id, settings, storage)
                await s.commit()
                ok += 1
            except Exception as e:  # noqa: BLE001
                await s.rollback()
                print(f"  ! {call.id}: {e}")
            n += 1
    await engine.dispose()
    print(f"перескорировано: {ok}/{n}")


asyncio.run(main())
