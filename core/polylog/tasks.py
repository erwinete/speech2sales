"""Procrastinate-контур (doc 01 §4.3, M1.5): очередь задач на PostgreSQL.

Импортируется лениво (worker/queue), чтобы dev/тесты без Postgres работали.
Контракт: одна задача process_call на звонок; стадии внутри идемпотентны
(state machine), ретраи с экспоненциальным backoff; DLQ — таблица
procrastinate_jobs со статусом failed (кнопка retry в UI — M2).
"""

from __future__ import annotations

import logging
import uuid

import procrastinate

from polylog.config import get_settings

log = logging.getLogger("polylog.tasks")


def pg_dsn(database_url: str) -> str:
    """SQLAlchemy-URL (postgresql+asyncpg://) → psycopg DSN (postgresql://)."""
    return database_url.replace("+asyncpg", "").replace("+psycopg", "")


def make_app(dsn: str | None = None) -> procrastinate.App:
    from procrastinate import psycopg_connector

    return procrastinate.App(
        connector=psycopg_connector.PsycopgConnector(
            conninfo=dsn or pg_dsn(get_settings().database_url)
        )
    )


app = make_app()


@app.task(
    name="process_call_task",  # стабильно для queue.configure_task (без пути модуля)
    queue="pipeline",
    retry=procrastinate.RetryStrategy(max_attempts=5, exponential_wait=3),
)
async def process_call_task(*, call_id: str) -> None:
    from polylog.db import make_engine, make_sessionmaker
    from polylog.pipeline import process_call
    from polylog.storage import make_storage

    settings = get_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            call = await process_call(session, uuid.UUID(call_id), settings, make_storage(settings))
            await session.commit()
            log.info("task: звонок %s → %s", call.id, call.state)
    finally:
        await engine.dispose()
