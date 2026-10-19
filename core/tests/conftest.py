"""Общие фикстуры тестов (pytest-asyncio auto). Границы подменяются tmp-каталогами;
внутренние коллабораторы (пайплайн, граф, stub-ASR) работают по-настоящему."""

import math
import struct
import wave
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from polylog.api.main import create_app
from polylog.config import Settings

AUTH = {"X-Api-Key": "test-token"}


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        storage_dir=str(tmp_path / "storage"),
        tmp_dir=str(tmp_path / "tmp"),
        api_token="test-token",
        asr_backend="stub",
        inline_process=True,
        autocreate_tables=True,
        _env_file=None,  # type: ignore[call-arg] — не читать .env пользователя
    )


def wav_bytes(seconds: float = 6.0, rate: int = 16_000, channels: int = 1) -> bytes:
    """Валидный 16 кГц PCM WAV (stdlib), синус — контент не важен для stub-ASR."""
    import io

    buf = io.BytesIO()
    total = int(seconds * rate)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(total):
            v = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            frame = struct.pack("<h", v)
            frames += frame if channels == 1 else frame * channels
        w.writeframes(bytes(frames))
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest_asyncio.fixture
async def session(settings: Settings):
    """Сессия БД с инициализированной схемой — для тестов сервисов без HTTP."""
    from polylog.db import init_db, make_engine, make_sessionmaker

    engine = make_engine(settings.database_url)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def app_client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app
