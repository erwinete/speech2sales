"""Alembic Environment (sync): URL из POLYLOG_DATABASE_URL (+psycopg для sync),
fallback — временный sqlite (для автогенерации baseline). Метаданные —
polylog.models (pgvector-таблица embeddings живёт вне ORM — её поднимает
docker-стенд, doc 03 §5)."""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polylog.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

url = None
for arg in context.get_x_argument(as_dictionary=True).get("url", ""), os.environ.get("POLYLOG_DATABASE_URL", ""):
    if arg:
        url = arg
        break
if not url:
    url = "sqlite:///./data/alembic-scratch.db"  # только для autogen/тестов
url = url.replace("+asyncpg", "+psycopg")  # alembic работает в sync-режиме
config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
