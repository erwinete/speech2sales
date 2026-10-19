"""Движок БД и сессии (SQLAlchemy 2.0 async)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polylog.models.base import Base


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Dev/тесты: create_all. Прод-миграции — alembic (doc 01 §7.4).
    Postgres: дополнительно pgvector-расширение и таблица эмбеддингов (doc 03 §5)."""
    from polylog import models  # noqa: F401 — регистрация таблиц

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
