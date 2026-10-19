"""Входная точка ASR/NLP-воркера (docker/Dockerfile.worker, профиль gpu/cpu).

Запуск: python -m polylog.worker
Схема очереди применяется заранее: procrastinate apply-schema --dsn ... (alembic-шаг M1.5).
"""

import asyncio
import logging
import os
import sys


def main() -> None:
    if sys.platform == "win32":
        # psycopg async несовместим с ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("polylog.worker")
    from polylog.tasks import app

    if os.environ.get("POLYLOG_PERIODIC") == "1":
        import polylog.periodic  # noqa: F401 — регистрация periodic-джоб

        log.info("periodic-джобы включены (риск-инсайты 06:00 daily)")
    log.info("worker запущен, очереди: pipeline")
    app.run_worker(queues=["pipeline"])


if __name__ == "__main__":
    main()
