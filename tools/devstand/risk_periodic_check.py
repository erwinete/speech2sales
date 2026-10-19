"""Живой прогон risk-recompute: defer задачи и ожидание инсайтов в БД."""

import asyncio
import sys
import time

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "core"))

DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"


async def defer_task() -> None:
    import polylog.periodic  # noqa: F401 — регистрация задачи (queue pipeline)
    from polylog.tasks import app

    with app.open():
        app.configure_task(name="recompute_risk_insights").defer()


async def wait_insights(timeout_s: float = 60.0) -> int:
    from sqlalchemy import text

    from polylog.db import make_engine, make_sessionmaker

    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    deadline = time.time() + timeout_s
    n = 0
    async with sm() as s:
        while time.time() < deadline:
            s.expire_all()
            n = (
                await s.execute(
                    text("SELECT count(*) FROM insights WHERE kind='risk_account'")
                )
            ).scalar_one()
            if n:
                break
            await asyncio.sleep(2)
    await engine.dispose()
    return n


asyncio.run(defer_task())
print("задача поставлена, жду инсайты…")
n = asyncio.run(wait_insights())
print(f"риск-инсайтов в ленте: {n}")
sys.exit(0 if n else 3)
