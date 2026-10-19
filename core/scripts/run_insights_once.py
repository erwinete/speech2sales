"""Разовый прогон refresh_insights по стенду: риск-инсайты + repeat_objection.
Эквивалент periodic-джобы 06:00, но запущенной вручную."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from polylog.config import get_settings
from polylog.db import make_engine, make_sessionmaker
from polylog.periodic import refresh_insights


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    async with sm() as session:
        counts = await refresh_insights(session)
    await engine.dispose()
    print(f"инсайты обновлены: risk_account={counts['risk_account']}, repeat_objection={counts['repeat_objection']}")


asyncio.run(main())
