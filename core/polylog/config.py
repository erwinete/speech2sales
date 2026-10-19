"""Конфигурация приложения (env с префиксом POLYLOG_, см. .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POLYLOG_", env_file=".env", extra="ignore")

    app_name: str = "polylog"
    debug: bool = False

    # Прод: postgresql+asyncpg://... (pgvector). Dev/тесты: sqlite+aiosqlite.
    database_url: str = "sqlite+aiosqlite:///./data/polylog-dev.db"
    # Автосоздание таблиц (dev/тесты); в проде — alembic-миграции (doc 01 §7.4)
    autocreate_tables: bool = True

    storage_dir: str = "./data/storage"
    tmp_dir: str = "./data/tmp"

    # Аутентификация API — skeleton: статический токен; полный RBAC/OIDC — doc 04 §5
    api_token: str = "dev-insecure-token"

    # ASR-бэкенд по умолчанию: "stub" (детерминированный, без ML-зависимостей).
    # Реальные: "gigaam-v3-rnnt", "t-one" — после бенчмарка M1 (doc 06 §6, ADR-4).
    asr_backend: str = "stub"

    # Dev: обрабатывать звонок синхронно в запросе. Прод: false → очередь
    # (procrastinate-воркеры, doc 01 §4.3; подключение — следующий шаг).
    inline_process: bool = True

    max_upload_mb: int = 200
    default_org_name: str = "default"

    # PII-политики (doc 04 §3): register — только регистр находок;
    # mask — маскировать в API-представлении. Экспорт маскируется отдельно:
    pii_action: str = "register"
    pii_export_action: str = "mask"

    # NLI-скоринг (ADR-14): каталог чекпойнта multitask_v2 (models/nli_rubert_v2
    # формата тренажёра). Пусто = NLI-стадия выключена.
    nli_model_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
