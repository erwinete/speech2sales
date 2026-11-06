"""Движок БД и сессии (SQLAlchemy 2.0 async)."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polylog.models.base import Base

log = logging.getLogger("polylog.db")

# R-12 (ТЗ v3.0 §8.1): NOT NULL-колонки без server_default в метаданных —
# запасные дефолты для ALTER TABLE ADD COLUMN на старых локальных базах.
_NOT_NULL_FALLBACK_DEFAULTS = {
    "is_active": "1",
    "poll_interval_min": "5",
    "calls_ingested_total": "0",
}


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _default_sql(col, dialect_name: str) -> str:
    """DEFAULT-фрагмент для NOT NULL колонок при ALTER TABLE ADD COLUMN."""
    if col.nullable is not False:
        return ""
    svd = col.server_default
    if svd is not None:
        arg = svd.arg
        if isinstance(arg, bool):
            return " DEFAULT TRUE" if arg else " DEFAULT FALSE"
        arg = str(arg)
        if arg.lower() in ("true", "false"):
            return f" DEFAULT {arg.upper()}"
        if arg.isdigit():
            return f" DEFAULT {arg}"
        return f" DEFAULT '{arg}'"
    fallback = _NOT_NULL_FALLBACK_DEFAULTS.get(col.name)
    if fallback is None:
        return ""
    if dialect_name == "postgresql" and fallback in ("0", "1"):
        return " DEFAULT TRUE" if fallback == "1" else " DEFAULT FALSE"
    return f" DEFAULT {fallback}"


async def _auto_migrate(engine: AsyncEngine) -> int:
    """Идемпотентная авто-миграция (R-12): новые колонки моделей добавляются
    в существующие таблицы через ALTER TABLE ... ADD COLUMN (try/except на
    каждую), чтобы старые локальные .db файлы обновлялись без пересоздания.
    Возвращает число фактически добавленных колонок."""
    from sqlalchemy import inspect as sa_inspect

    def _existing(sync_conn):
        insp = sa_inspect(sync_conn)
        return {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}

    added = 0
    dialect_name = engine.url.get_backend_name()
    dialect = engine.dialect
    async with engine.begin() as conn:
        existing = await conn.run_sync(_existing)
        for table in Base.metadata.sorted_tables:
            cols = existing.get(table.name)
            if cols is None:
                continue  # новая таблица — создана create_all
            for col in table.columns:
                if col.name in cols:
                    continue
                stmt = (
                    f"ALTER TABLE {table.name} ADD COLUMN {col.name} "
                    f"{col.type.compile(dialect)}{_default_sql(col, dialect_name)}"
                )
                try:
                    await conn.execute(text(stmt))
                    added += 1
                except Exception as e:  # noqa: BLE001 — идемпотентность колонки
                    log.warning("auto-migrate %s: %s", stmt, e)
    return added


async def init_db(engine: AsyncEngine) -> None:
    """Dev/тесты: create_all + авто-миграция колонок. Прод-миграции — alembic
    (doc 01 §7.4). Postgres: дополнительно pgvector-расширение и таблица
    эмбеддингов (doc 03 §5)."""
    from polylog import models  # noqa: F401 — регистрация таблиц

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _auto_migrate(engine)

    if engine.url.get_backend_name().startswith("postgresql"):
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # halfvec(768) — USER2-base; индекс HNSW добавляется при первом наполнении
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id bigserial PRIMARY KEY,
                    org_id uuid NOT NULL,
                    entity_type text NOT NULL CHECK (entity_type IN
                        ('call','utterance','company_profile','product','objection_pattern')),
                    entity_id text NOT NULL,
                    model_id text NOT NULL,
                    dim int NOT NULL,
                    vector halfvec(768) NOT NULL,
                    meta jsonb,
                    created_at timestamptz DEFAULT now(),
                    UNIQUE (entity_type, entity_id, model_id)
                )
            """))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_embeddings_org_type ON embeddings (org_id, entity_type)"
            ))
