"""Точка постановки задач из API (ленивый импорт procrastinate)."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid

log = logging.getLogger("polylog.queue")

if sys.platform == "win32":
    # psycopg async несовместим с ProactorEventLoop (dev-машины на Windows)
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def enqueue_process_call(call_id: uuid.UUID) -> bool:
    """Ставит задачу обработки звонка. False — procrastinate недоступен
    (звонок останется в discovered; inline-режим или воркер разберут)."""
    try:
        from polylog.tasks import app as _procrastinate_app
        from polylog.tasks import process_call_task  # noqa: F401 — регистрация задачи

        procrastinate_app = _procrastinate_app
    except ImportError as e:  # pragma: no cover — extra [worker] не установлен
        log.warning("procrastinate недоступен (%s): звонок %s остался в очереди БД", e, call_id)
        return False

    def _enqueue_sync() -> None:
        with procrastinate_app.open():
            procrastinate_app.configure_task(name="process_call_task").defer(
                call_id=str(call_id)
            )

    try:
        _enqueue_sync()
        return True
    except Exception as e:  # noqa: BLE001 — очередь недоступна не должна ронять API
        log.error("не удалось поставить задачу для %s: %s", call_id, e)
        return False
