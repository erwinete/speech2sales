"""Нативный MCP-сервер «Полилога» (ТЗ v3.0 §4.5): JSON-RPC 2.0 без внешних
зависимостей. Два транспорта: stdio (polylog.mcp.cli) и HTTP (POST /api/v1/mcp/rpc
+ SSE GET /api/v1/mcp/sse). Пять тулзов отдают агенту те же три среза данных,
что AI Lab, с автоматической очисткой ПДн (sanitize_pii=True по умолчанию)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from polylog.llm import context_builder as cb
from polylog.pii.sanitizer import PiiSanitizerConfig, SanitizerSession

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "polylog-analytics"
SERVER_VERSION = "0.2.0"

_BOOL_SCHEMA = {
    "type": "boolean",
    "default": True,
    "description": "Очищать ПДн (152-ФЗ): ФИО → [ФИО_1], телефоны → [ТЕЛЕФОН_1], UUID → [CALL_#1]",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "polylog_get_problematic_calls",
        "description": (
            "Проблемные и рисковые звонки/контакты из предиктивной аналитики: зона риска "
            "Scorecard/CatBoost, повторяющиеся неотработанные возражения (Unresolved Repeat), "
            "звонки с низким скором или негативной тональностью."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "risk_band": {"type": "string", "enum": ["high", "medium"], "default": "high"},
                "max_score": {"type": "number", "default": 50.0, "description": "Порог низкого скора звонка"},
                "limit": {"type": "integer", "default": 20},
                "sanitize_pii": _BOOL_SCHEMA,
            },
        },
    },
    {
        "name": "polylog_get_rubert_scoring_results",
        "description": (
            "Результаты оценки звонков по чек-листам (рубрикам): цитаты-доказательства, "
            "вердикты RuBERT-NLI о ответах на вопросы клиентов, нарушения и статистика "
            "отработки возражений."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "days": {"type": "integer", "default": 30},
                "agent_name": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
                "sanitize_pii": _BOOL_SCHEMA,
            },
        },
    },
    {
        "name": "polylog_get_transcripts_by_period",
        "description": (
            "Полные транскрипты звонков с ролями (Менеджер/Клиент), таймкодами и метриками "
            "речи за выбранный интервал дат."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "direction": {"type": "string", "enum": ["inbound", "outbound", "internal"]},
                "agent_name": {"type": "string"},
                "objection_type": {"type": "string"},
                "min_duration_sec": {"type": "integer", "default": 15},
                "limit": {"type": "integer", "default": 25},
                "sanitize_pii": _BOOL_SCHEMA,
            },
        },
    },
    {
        "name": "polylog_get_call_details",
        "description": (
            "Детальный разбор одного звонка: все реплики, метрики, возражения, сигналы "
            "покупки, нарушения и пункты скоринга. Принимает UUID звонка или алиас "
            "[CALL_#N] из предыдущих вызовов в этой сессии."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "call_id": {"type": "string"},
                "sanitize_pii": _BOOL_SCHEMA,
            },
            "required": ["call_id"],
        },
    },
    {
        "name": "polylog_get_team_coaching_summary",
        "description": (
            "Сводная матрица эффективности менеджеров: звонки, средний балл, отработка "
            "возражений, нарушения — основа плана коучинга."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "sanitize_pii": _BOOL_SCHEMA,
            },
        },
    },
]


# ── регистрация алиасов сессии ──


def _remember_aliases(registry: dict[str, str], stats: dict) -> None:
    """Алиасы [CALL_#1] → UUID сохраняются на время MCP-сессии, чтобы
    polylog_get_call_details принимал ссылку из отчёта LLM."""
    for alias, real in (stats or {}).get("alias_map", {}).items():
        if alias.startswith("[CALL_#") or alias.startswith("[CONTACT_#") or alias.startswith("[DEAL_#"):
            registry[alias] = real


def _resolve_call_id(registry: dict[str, str], call_id: str) -> uuid.UUID:
    raw = (call_id or "").strip()
    real = registry.get(raw, raw)
    return uuid.UUID(real)


# ── тулзы ──


async def _tool_problematic(session, org, registry, args) -> str:
    bundle = await cb.build_context(
        session, org, mode="problematic_calls",
        days=int(args.get("days", 30)),
        risk_band=args.get("risk_band", "high"),
        score_max=args.get("max_score", 50.0),
        limit_calls=int(args.get("limit", 20)),
    )
    if args.get("sanitize_pii", True):
        cb.apply_pii(bundle)
    _remember_aliases(registry, bundle.stats)
    return bundle.markdown


async def _tool_rubert(session, org, registry, args) -> str:
    bundle = await cb.build_context(
        session, org, mode="rubert_scores",
        date_from=args.get("date_from"), date_to=args.get("date_to"),
        days=int(args.get("days", 30)),
        agent_name=args.get("agent_name"),
        limit_calls=int(args.get("limit", 30)),
    )
    if args.get("sanitize_pii", True):
        cb.apply_pii(bundle)
    _remember_aliases(registry, bundle.stats)
    return bundle.markdown


async def _tool_transcripts(session, org, registry, args) -> str:
    bundle = await cb.build_context(
        session, org, mode="transcripts_range",
        date_from=args.get("date_from"), date_to=args.get("date_to"),
        days=int(args.get("days", 30)),
        agent_name=args.get("agent_name"),
        direction=args.get("direction"),
        objection_type=args.get("objection_type"),
        min_duration_sec=int(args.get("min_duration_sec", 15)),
        limit_calls=int(args.get("limit", 25)),
    )
    if args.get("sanitize_pii", True):
        cb.apply_pii(bundle)
    _remember_aliases(registry, bundle.stats)
    return bundle.markdown


async def _tool_call_details(session, org, registry, args) -> str:
    call_uuid = _resolve_call_id(registry, args.get("call_id", ""))
    data = await cb.call_detail_bundle(session, org, call_uuid)
    if data is None:
        raise ValueError(f"звонок {args.get('call_id')} не найден")
    if args.get("sanitize_pii", True):
        sanitizer = SanitizerSession(PiiSanitizerConfig())
        data["call_alias"] = sanitizer.register_id("call", data["call_id"])
        data.pop("call_id", None)
        if data.get("external_id"):
            data["external_id"] = sanitizer.register_internal_id(str(data["external_id"]), "EXT_")
        for f in ("phone_from", "phone_to"):
            if data.get(f):
                data[f] = sanitizer.register_known_phone(data[f])
        if data.get("agent_name"):
            data["agent_name"] = sanitizer.register_known_name(data["agent_name"])
        data = sanitizer.sanitize_obj(data)
        _remember_aliases(registry, sanitizer.summary())
    return json.dumps(data, ensure_ascii=False, indent=1)


async def _tool_coaching(session, org, registry, args) -> str:
    items = await cb.team_coaching_summary(session, org, days=int(args.get("days", 30)))
    if args.get("sanitize_pii", True):
        sanitizer = SanitizerSession(PiiSanitizerConfig())
        for it in items:
            it["agent"] = sanitizer.sanitize_value(it["agent"], "names", "AGENT")
        _remember_aliases(registry, sanitizer.summary())
    lines = ["# Коучинг-сводка команды", ""]
    lines.append("| Менеджер | Звонков | Средний балл | Возражений | Отработано | Нарушений |")
    lines.append("|---|---|---|---|---|---|")
    for it in items:
        avg = it["avg_score"] if it["avg_score"] is not None else "—"
        ratio = it["objections_handled_ratio"] if it["objections_handled_ratio"] is not None else "—"
        lines.append(
            f"| {it['agent']} | {it['calls_total']} | {avg} | {it['objections_total']} | {ratio} | {it['violations']} |"
        )
    return "\n".join(lines)


_TOOL_HANDLERS = {
    "polylog_get_problematic_calls": _tool_problematic,
    "polylog_get_rubert_scoring_results": _tool_rubert,
    "polylog_get_transcripts_by_period": _tool_transcripts,
    "polylog_get_call_details": _tool_call_details,
    "polylog_get_team_coaching_summary": _tool_coaching,
}


# ── JSON-RPC 2.0 ──

RPC_ERRORS = {
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
    -32603: "Internal error",
}


def _rpc_error(code: int, message: str | None = None, request_id: Any = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message or RPC_ERRORS.get(code, "Error")},
    }


def _rpc_result(result: Any, request_id: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def handle_rpc(
    payload: dict[str, Any],
    session,
    org,
    registry: dict[str, str],
) -> dict | None:
    """Один запрос JSON-RPC 2.0 → ответ. None для уведомлений (R-07):
    сообщения без id и любые notifications/* не получают ответа — в stdio
    в stdout ничего не пишется, в HTTP возвращается 202/204."""
    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params") or {}
    if "id" not in payload:
        return None  # уведомление — ответ не отправляется
    if isinstance(method, str) and method.startswith("notifications/"):
        return None  # notifications/initialized и т.п. — даже с id
    if not isinstance(method, str):
        return _rpc_error(-32600, None, request_id)

    if method == "initialize":
        return _rpc_result(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
            request_id,
        )
    if method == "ping":
        return _rpc_result({}, request_id)
    if method == "tools/list":
        return _rpc_result({"tools": TOOLS}, request_id)
    if method == "resources/list":
        return _rpc_result({"resources": []}, request_id)
    if method == "prompts/list":
        return _rpc_result({"prompts": []}, request_id)
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return _rpc_error(-32602, f"неизвестный тулз: {name}", request_id)
        try:
            text = await handler(session, org, registry, args)
        except ValueError as e:
            return _rpc_result(
                {"content": [{"type": "text", "text": str(e)}], "isError": True}, request_id
            )
        except Exception as e:  # noqa: BLE001 — наружу уходит сообщение, не трейс
            return _rpc_error(-32603, str(e)[:300], request_id)
        return _rpc_result({"content": [{"type": "text", "text": text}], "isError": False}, request_id)

    return _rpc_error(-32601, None, request_id)
