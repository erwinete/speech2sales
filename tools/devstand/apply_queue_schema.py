"""Применение схемы procrastinate к целевой БД (sync-режим, Windows-совместимо)."""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "core"))

dsn = sys.argv[1] if len(sys.argv) > 1 else "postgresql://polylog:polylog@localhost:5432/polylog"

from procrastinate import App, psycopg_connector  # noqa: E402

app = App(connector=psycopg_connector.PsycopgConnector(conninfo=dsn))
with app.open():
    app.schema_manager.apply_schema()
print("schema applied to", dsn)
