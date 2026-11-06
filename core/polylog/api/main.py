"""FastAPI-приложение «Полилога» (doc 01 §4.2): тонкая сборка create_app —
lifespan, CORS, подключение доменных роутеров, глобальные обработчики.
Вся логика эндпоинтов — в polylog/api/routers/ (ТЗ §3.1)."""

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from polylog.api.routers import ALL_ROUTERS
from polylog.config import Settings
from polylog.config import get_settings as _default_settings
from polylog.db import init_db, make_engine, make_sessionmaker
from polylog.storage import StorageError, make_storage

log = logging.getLogger("polylog.api")


async def _ensure_default_admin(sessionmaker, org_id: uuid.UUID, settings: Settings) -> None:
    """Дефолтный администратор при первом старте (ТЗ §4.2): email
    admin@polylog.local, пароль POLYLOG_ADMIN_PASSWORD (по умолчанию admin123)."""
    import os

    from sqlalchemy import select

    from polylog.api.routers.auth import hash_password
    from polylog.models.system import User

    async with sessionmaker() as session:
        existing = (await session.execute(select(User))).scalars().first()
        if existing is not None:
            return
        session.add(
            User(
                org_id=org_id,
                email="admin@polylog.local",
                display_name="Администратор",
                role="admin",
                password_hash=hash_password(os.environ.get("POLYLOG_ADMIN_PASSWORD", "admin123")),
                is_active=True,
            )
        )
        await session.commit()
        log.warning(
            "создан дефолтный админ admin@polylog.local — смените пароль после первого входа"
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or _default_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    storage = make_storage(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.tmp_dir).mkdir(parents=True, exist_ok=True)
        if settings.autocreate_tables:
            await init_db(engine)
        from polylog.graph.service import get_default_org

        async with sessionmaker() as session:
            org = await get_default_org(session)
            await session.commit()
        app.state.default_org = org
        await _ensure_default_admin(sessionmaker, org.id, settings)
        log.warning(
            "API-токен: %s — замените POLYLOG_API_TOKEN перед боевым запуском (doc 04)",
            "дефолтный dev-токен" if settings.api_token == "dev-insecure-token" else "из конфига",
        )
        yield

    app = FastAPI(title="Polylog Speech Analytics", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.storage = storage

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": app.version})

    for r in ALL_ROUTERS:
        app.include_router(r)

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError) -> JSONResponse:
        log.error("ошибка хранилища: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "внутренняя ошибка хранилища"})

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("polylog.api.main:app", host="127.0.0.1", port=8000, reload=False)
