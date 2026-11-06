"""Роутер коннекторов (ТЗ §4.3-B, §7.1): каталог, CRUD, verify, sync, webhooks."""  # noqa: E501

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from polylog.api.deps import AdminDep, AdminOrSupervisorDep, SessionDep
from polylog.api.schemas.connectors import ConnectorCreate, ConnectorUpdate
from polylog.ingest.base import ConnectorError
from polylog.ingest.registry import get_connector
from polylog.models.system import AuditLog, Connector

router = APIRouter(prefix="/api/v1", tags=["connectors"])

SECRET_KEYS = {"password", "api_key", "access_token", "oauth_token", "webhook_key",
               "client_secret", "hook_secret", "dsn", "key_path"}
MASK = "••••••••"


def _hook_header(x_hook_signature: str | None = Header(default=None)):
    return x_hook_signature

CONNECTOR_CATALOG: list[dict[str, Any]] = [
    {"kind": "amocrm", "title": "amoCRM (v4 REST + OAuth 2.0)", "category": "crm",
     "modes": ["pull", "push", "webhook"],
     "description": "Синхронизация контактов, сделок и звонков через API v4 amoCRM.",
     "fields": [
         {"name": "subdomain", "label": "Поддомен amoCRM", "type": "text", "required": True, "secret": False, "placeholder": "company (без .amocrm.ru)"},
         {"name": "access_token", "label": "Long-lived / OAuth Access Token", "type": "password", "required": True, "secret": True, "placeholder": "eyJ0eXAiOiJKV1Qi..."},
         {"name": "client_id", "label": "ID интеграции (Client ID)", "type": "text", "required": False, "secret": False, "placeholder": "UUID интеграции"},
         {"name": "client_secret", "label": "Секретный ключ (Client Secret)", "type": "password", "required": False, "secret": True, "placeholder": "Секрет для авто-обновления токена"},
         {"name": "hook_secret", "label": "HMAC-секрет вебхука (X-Hook-Signature)", "type": "password", "required": False, "secret": True, "placeholder": "Опциональный ключ подписи вебхуков"},
     ]},
    {"kind": "bitrix24", "title": "Битрикс24 (Телефония Voximplant & CRM)", "category": "crm",
     "modes": ["webhook", "pull"],
     "description": "Приём вебхуков onVoximplantCallEnd и выгрузка статистики voximplant.statistic.get.",
     "fields": [
         {"name": "portal", "label": "Адрес портала Битрикс24", "type": "text", "required": True, "secret": False, "placeholder": "company.bitrix24.ru"},
         {"name": "user_id", "label": "ID пользователя вебхука", "type": "text", "required": True, "secret": False, "placeholder": "1"},
         {"name": "webhook_key", "label": "Код входящего вебхука (REST)", "type": "password", "required": False, "secret": True, "placeholder": "abc123xyz..."},
         {"name": "oauth_token", "label": "OAuth-токен приложения (альтернатива)", "type": "password", "required": False, "secret": True, "placeholder": "Пусто при webhook_key"},
         {"name": "hook_secret", "label": "HMAC-секрет исходящего вебхука", "type": "password", "required": False, "secret": True, "placeholder": "Секрет X-Hook-Signature"},
     ]},
    {"kind": "freepbx", "title": "FreePBX / Asterisk (CDR + Monitor)", "category": "pbx",
     "modes": ["pull"],
     "description": "Чтение таблицы cdr Asterisk и записей из /var/spool/asterisk/monitor.",
     "fields": [
         {"name": "monitor_dir", "label": "Каталог записей (monitor)", "type": "text", "required": True, "secret": False, "placeholder": "/var/spool/asterisk/monitor"},
     ]},
    {"kind": "mightycall", "title": "MightyCall (Облачная АТС)", "category": "pbx",
     "modes": ["pull", "webhook"],
     "description": "Список звонков и записей по REST API MightyCall.",
     "fields": [
         {"name": "base_url", "label": "Base URL API", "type": "text", "required": True, "secret": False, "placeholder": "https://api.mightycall.io/v1"},
         {"name": "api_key", "label": "Bearer API Key", "type": "password", "required": True, "secret": True, "placeholder": "Ключ доступа API"},
         {"name": "hook_secret", "label": "HMAC-секрет вебхука", "type": "password", "required": False, "secret": True, "placeholder": "Опционально"},
     ]},
    {"kind": "oktell", "title": "Oktell (MS SQL CDR + Записи)", "category": "pbx",
     "modes": ["pull"],
     "description": "Интеграция с АТС Октелл через MS SQL и сетевую папку записей.",
     "fields": [
         {"name": "dsn", "label": "SQLAlchemy DSN базы Oktell", "type": "password", "required": True, "secret": True, "placeholder": "mssql+pymssql://user:pass@oktell-db/oktell"},
         {"name": "records_dir", "label": "Каталог записей (Records)", "type": "text", "required": False, "secret": False, "placeholder": "/mnt/oktell/records"},
     ]},
    {"kind": "cisco_ucm", "title": "Cisco Unified CM / CUBE (CDR CSV)", "category": "pbx",
     "modes": ["pull"],
     "description": "Импорт flat CDR-файлов (cdr_flat_*.csv) и записей Cisco MediaSense.",
     "fields": [
         {"name": "cdr_dir", "label": "Каталог CDR", "type": "text", "required": True, "secret": False, "placeholder": "./data/cisco-cdr"},
     ]},
    {"kind": "sftp-monitor", "title": "Универсальный SFTP-монитор записей", "category": "pbx",
     "modes": ["pull"],
     "description": "Подключение по SSH/SFTP к любой АТС, скачивание записей и извлечение номера по regexp.",
     "fields": [
         {"name": "host", "label": "SFTP Хост / IP", "type": "text", "required": True, "secret": False, "placeholder": "192.168.1.10"},
         {"name": "port", "label": "Порт SSH", "type": "number", "required": True, "secret": False, "placeholder": "22"},
         {"name": "username", "label": "Пользователь SSH", "type": "text", "required": True, "secret": False, "placeholder": "asterisk"},
         {"name": "password", "label": "Пароль SSH", "type": "password", "required": False, "secret": True, "placeholder": "Пароль (или ключ)"},
         {"name": "key_path", "label": "Путь к приватному SSH-ключу", "type": "text", "required": False, "secret": False, "placeholder": "/app/keys/id_ed25519"},
         {"name": "remote_dir", "label": "Удалённый каталог записей", "type": "text", "required": True, "secret": False, "placeholder": "/var/spool/asterisk/monitor"},
         {"name": "pattern", "label": "Маска файлов (fnmatch)", "type": "text", "required": True, "secret": False, "placeholder": "*.wav"},
         {"name": "name_regex", "label": "RegExp извлечения номера (?P<num>...)", "type": "text", "required": True, "secret": False, "placeholder": "(?P<num>\\+?\\d{6,15})"},
     ]},
    {"kind": "sql-cdr", "title": "Универсальный SQL-CDR коннектор", "category": "pbx",
     "modes": ["pull"],
     "description": "Чтение CDR-таблицы из внешней СУБД с настраиваемым маппингом колонок.",
     "fields": [
         {"name": "dsn", "label": "SQLAlchemy DSN внешней БД", "type": "password", "required": True, "secret": True, "placeholder": "postgresql://reader:pass@pbx-db:5432/asterisk"},
         {"name": "table_name", "label": "Таблица CDR", "type": "text", "required": True, "secret": False, "placeholder": "cdr"},
     ]},
]


def _mask_config(config: dict) -> dict:
    return {k: (MASK if k in SECRET_KEYS and v else v) for k, v in (config or {}).items()}


@router.get("/connectors/catalog")
async def connectors_catalog(_: AdminOrSupervisorDep) -> dict:
    return {"items": CONNECTOR_CATALOG}


@router.get("/connectors")
async def list_connectors(session: SessionDep, user: AdminOrSupervisorDep, request: Request) -> dict:
    rows = (
        (
            await session.execute(
                select(Connector).where(Connector.org_id == user.org_id).order_by(Connector.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "kind": r.kind,
                "display_name": r.display_name,
                "config": _mask_config(r.config),
                "status": r.status,
                "poll_interval_min": r.poll_interval_min,
                "last_poll_at": r.last_poll_at.isoformat() if r.last_poll_at else None,
                "last_error": r.last_error,
                "calls_ingested_total": r.calls_ingested_total,
                "webhook_url": f"{request.base_url}api/v1/hooks/{r.kind}",
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


def _build_connector_instance(row: Connector):
    config = dict(row.config or {})
    # секреты из secrets_encrypted (демо-хранилище: base64 JSON; прод — KMS)
    if row.secrets_encrypted:
        try:
            config.update(json.loads(row.secrets_encrypted))
        except Exception:  # noqa: BLE001
            pass
    return get_connector(row.kind, config)


@router.post("/connectors")
async def create_connector(body: ConnectorCreate, session: SessionDep, actor: AdminDep, request: Request) -> dict:
    try:
        get_connector(body.kind, body.config)
    except ConnectorError as e:
        raise HTTPException(422, str(e)) from e
    row = Connector(
        org_id=actor.org_id,
        kind=body.kind,
        display_name=body.display_name,
        config=body.config,
        secrets_encrypted=json.dumps(body.secrets) if body.secrets else None,
        status=body.status,
        poll_interval_min=body.poll_interval_min,
    )
    session.add(row)
    await session.flush()
    _audit(session, actor, "connector_create", str(row.id), {"kind": body.kind})
    await session.commit()
    return {
        "id": str(row.id), "kind": row.kind, "display_name": row.display_name,
        "config": _mask_config(row.config), "status": row.status,
        "poll_interval_min": row.poll_interval_min,
        "last_poll_at": None, "last_error": None, "calls_ingested_total": 0,
        "webhook_url": f"{request.base_url}api/v1/hooks/{row.kind}",
        "created_at": row.created_at.isoformat(),
    }


def _audit(session, actor, action: str, resource_id: str, details: dict | None = None) -> None:
    session.add(
        AuditLog(
            org_id=actor.org_id, actor_id=actor.user_id, action=action,
            resource_type="connector", resource_id=resource_id, details=details,
        )
    )


async def _get_own_connector(session, connector_id: uuid.UUID, org_id) -> Connector:
    row = await session.get(Connector, connector_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(404, "коннектор не найден")
    return row


@router.patch("/connectors/{connector_id}")
async def update_connector(
    connector_id: uuid.UUID, body: ConnectorUpdate, session: SessionDep, actor: AdminDep
) -> dict:
    row = await _get_own_connector(session, connector_id, actor.org_id)
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.config is not None:
        row.config = body.config
    if body.secrets is not None:
        old = json.loads(row.secrets_encrypted) if row.secrets_encrypted else {}
        merged = {k: v for k, v in body.secrets.items() if v != MASK}
        row.secrets_encrypted = json.dumps({**old, **merged})
    if body.status is not None:
        row.status = body.status
    if body.poll_interval_min is not None:
        row.poll_interval_min = body.poll_interval_min
    _audit(session, actor, "connector_update", str(row.id))
    await session.commit()
    return {"id": str(row.id), "status": row.status}


@router.delete("/connectors/{connector_id}")
async def delete_connector(connector_id: uuid.UUID, session: SessionDep, actor: AdminDep) -> dict:
    row = await _get_own_connector(session, connector_id, actor.org_id)
    from polylog.models.calls import Call

    call_rows = (
        (
            await session.execute(
                select(Call).where(Call.org_id == actor.org_id, Call.connector_id == row.id)
            )
        )
        .scalars()
        .all()
    )
    for c in call_rows:
        c.connector_id = None
    await session.delete(row)
    _audit(session, actor, "connector_delete", str(connector_id))
    await session.commit()
    return {"id": str(connector_id), "deleted": True, "unbound_calls": len(call_rows)}


@router.post("/connectors/{connector_id}/verify")
async def verify_connector(connector_id: uuid.UUID, session: SessionDep, user: AdminOrSupervisorDep) -> dict:
    row = await _get_own_connector(session, connector_id, user.org_id)
    try:
        instance = _build_connector_instance(row)
        result = await asyncio.to_thread(instance.verify)
        row.last_error = None if result.get("ok") else str(result.get("error", "verify failed"))
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": str(e)}
        row.last_error = str(e)
    row.last_poll_at = datetime.now(UTC)
    await session.commit()
    return {"ok": result.get("ok", False), "details": result, "checked_at": row.last_poll_at.isoformat()}


async def sync_connector(session, actor_or_user, row: Connector, settings, storage, since_days: int = 7, limit: int = 50) -> dict:
    """Цикл синхронизации: discover → download → create_call_from_ref → process/enqueue."""
    from polylog.graph.service import get_default_org
    from polylog.ingest.service import create_call_from_ref
    from polylog.pipeline import process_call

    org = await get_default_org(session)
    instance = _build_connector_instance(row)
    since = datetime.now(UTC) - timedelta(days=since_days)
    errors: list[str] = []
    discovered = created = duplicates = 0
    try:
        refs = await asyncio.to_thread(instance.discover, since, limit)
        discovered = len(refs)
        for ref in refs:
            try:
                audio = None
                if ref.recording_uri:
                    try:
                        audio = await asyncio.to_thread(instance.download, ref)
                    except Exception as e:  # noqa: BLE001 — запись может быть ещё не готова
                        errors.append(f"{ref.external_id}: download: {e}")
                        continue
                call = await create_call_from_ref(
                    session, org, row, ref, storage, audio=audio, source=row.kind
                )
                if call is None:
                    duplicates += 1
                    continue
                created += 1
                row.calls_ingested_total += 1
                if settings.inline_process and audio:
                    try:
                        await process_call(session, call.id, settings, storage)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{ref.external_id}: pipeline: {e}")
                elif audio:
                    from polylog.queue import enqueue_process_call

                    enqueue_process_call(call.id)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{ref.external_id}: {e}")
        row.last_poll_at = datetime.now(UTC)
        row.last_error = errors[0] if errors else None
    except Exception as e:  # noqa: BLE001
        row.last_error = str(e)
        errors.append(str(e))
    await session.commit()
    return {"discovered": discovered, "created": created,
            "skipped_duplicates": duplicates, "errors": errors}


@router.post("/connectors/{connector_id}/sync")
async def sync_connector_impl(
    connector_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    user: AdminOrSupervisorDep,
    since_days: int = 7,
    limit: int = 50,
) -> dict:
    row = await _get_own_connector(session, connector_id, user.org_id)
    return await sync_connector(
        session, user, row, request.app.state.settings, request.app.state.storage,
        since_days=since_days, limit=limit,
    )


# ── Webhooks (перенос из main.py, контракт сохранён) ──

import hashlib  # noqa: E402
import hmac as hmac_mod  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402


def _hook_secret(connector: str) -> str | None:
    return os.environ.get(f"POLYLOG_HOOK_SECRET_{connector.upper()}")


@router.post("/hooks/{connector}", status_code=202)
async def connector_hook(
    connector: str,
    request: Request,
    session: SessionDep,
    x_hook_signature: Annotated[str | None, Depends(_hook_header)] = None,
) -> JSONResponse:
    """Webhook-приём событий телефонии/CRM (doc 02 §1.1, doc 04 §1)."""
    from polylog.ingest.service import create_call_from_ref
    from polylog.models.calls import Call
    from polylog.pipeline import process_call

    body = await request.body()
    if not body:
        raise HTTPException(422, "пустой payload")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"payload не JSON: {e}") from e

    try:
        conn = get_connector(connector, {})
    except ConnectorError:
        raise HTTPException(404, f"коннектор {connector!r} не зарегистрирован") from None

    secret = _hook_secret(connector)
    if secret:
        expected = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not x_hook_signature or not hmac_mod.compare_digest(x_hook_signature, expected):
            raise HTTPException(401, "неверная подпись X-Hook-Signature")

    parse = getattr(conn, "parse", None)
    if parse is None:
        try:
            mod = sys.modules[conn.__class__.__module__]
        except KeyError:
            raise HTTPException(422, f"коннектор {connector!r} не поддерживает webhook") from None
        parse = getattr(mod, "parse_call_element", None) or getattr(mod, "parse_call_json", None)
        if parse is None:
            raise HTTPException(422, f"коннектор {connector!r} не поддерживает webhook-приём")
    ref = parse(payload)
    if ref is None:
        return {"status": "skipped", "reason": "payload без звонка с записью"}

    from polylog.graph.service import get_default_org

    org = await get_default_org(session)
    connector_row = await get_or_create_connector(session, org.id, connector, {})
    call = await create_call_from_ref(
        session, org, connector_row, ref, request.app.state.storage, source="connector"
    )
    created = call is not None
    if not created:
        call = (
            (
                await session.execute(
                    select(Call).where(
                        Call.org_id == org.id,
                        Call.external_id == ref.external_id,
                        Call.connector_id == connector_row.id,
                    )
                )
            )
            .scalar_one()
        )
    if created and ref.recording_uri and request.app.state.settings.inline_process:
        try:
            call = await process_call(session, call.id, request.app.state.settings, request.app.state.storage)
        except Exception as e:  # noqa: BLE001
            log.warning("webhook-звонок %s: пайплайн упал: %s", call.id, e)
    await session.commit()
    await session.refresh(call)
    return {
        "status": "ok", "created": created,
        "call_id": str(call.id), "state": call.state,
        "reason": None if ref.recording_uri else "без записи — пайплайн отложен",
    }


import logging  # noqa: E402

from fastapi import Header  # noqa: E402
from sqlalchemy import select  # noqa: E402

from polylog.ingest.service import get_or_create_connector  # noqa: E402

log = logging.getLogger("polylog.api.connectors")


def _hook_header(x_hook_signature: str | None = Header(default=None)):
    return x_hook_signature
