"""Роутер AI Lab (ТЗ v3.0 §4.4-4.5): /api/v1/ai/* — пресеты, предпросмотр
контекста с очисткой ПДн, запуск LLM-анализа (OpenRouter/OpenAI-compatible),
история разборов, MCP-конфиги; /api/v1/mcp/* — HTTP-транспорт MCP-сервера
(JSON-RPC POST + SSE)."""

import asyncio
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from polylog.api.deps import AuthDep, CurrentUser, SessionDep, require_role
from polylog.api.schemas.llm import AIAnalyzeRequest, AIContextRequest
from polylog.graph.service import get_default_org
from polylog.llm import client as llm_client
from polylog.llm.context_builder import apply_pii, build_context
from polylog.llm.prompts import DEFAULT_SYSTEM_PROMPT, PRESETS, RECOMMENDED_MODELS
from polylog.mcp.server import TOOLS, handle_rpc
from polylog.models.system import AuditLog, LLMAnalysisRun, Org

log = logging.getLogger("polylog.api.ai")

router = APIRouter(prefix="/api/v1", tags=["ai-analysis"])

RequireAnalyst = Annotated[CurrentUser, Depends(require_role("admin", "supervisor", "analyst"))]


def _mask_key(key: str | None) -> str | None:
    if not key:
        return None
    return key[:8] + "…" + key[-4:] if len(key) > 14 else "***"


async def _org(session) -> Org:
    return await get_default_org(session)


def _stats_out(stats: dict | None) -> dict:
    """SanitizerSession.summary() → стабильный шейп для API и llm_analysis_runs."""
    stats = stats or {}
    return {
        "enabled": stats.get("enabled", True),
        "total_redactions": stats.get("total_redactions", 0),
        "by_category": stats.get("by_category", {}),
        "alias_map": stats.get("alias_map", {}),
    }


# ── AI Lab ──


@router.get("/ai/presets")
async def presets(session: SessionDep, _: AuthDep) -> dict:
    org = await _org(session)
    saved_key = (org.settings or {}).get("llm_api_key")
    return {
        "presets": [
            {
                "id": p["id"], "title": p["title"], "mode": p["mode"],
                "system_prompt": p["system_prompt"] or DEFAULT_SYSTEM_PROMPT,
                "user_prompt": p["user_prompt"],
            }
            for p in PRESETS
        ],
        "recommended_models": RECOMMENDED_MODELS,
        "system_prompt_default": DEFAULT_SYSTEM_PROMPT,
        "provider_settings": {
            "base_url": (org.settings or {}).get("llm_base_url") or "https://openrouter.ai/api/v1",
            "api_key_masked": _mask_key(saved_key),
            "model": (org.settings or {}).get("llm_model"),
        },
    }


@router.post("/ai/preview-context")
async def preview_context(body: AIContextRequest, session: SessionDep, user: RequireAnalyst) -> dict:
    org = await _org(session)
    try:
        bundle = await build_context(
            session, org, mode=body.mode,
            date_from=body.date_from, date_to=body.date_to, days=body.days,
            agent_user_id=body.agent_user_id, agent_name=body.agent_name,
            risk_band=body.risk_band, score_max=body.score_max,
            direction=body.direction, min_duration_sec=body.min_duration_sec,
            objection_type=body.objection_type, call_ids=body.call_ids,
            limit_calls=body.limit_calls,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    apply_pii(bundle, body.pii)
    return {
        "mode": bundle.mode,
        "calls_matched": bundle.calls_count,
        "estimated_tokens": bundle.estimated_tokens,
        "pii_stats": _stats_out(bundle.stats),
        "context_preview": bundle.markdown,
        "structured_bundle": bundle.structured,
    }


async def _prepare_analyze(body: AIAnalyzeRequest, session, user: RequireAnalyst):
    """Общая подготовка analyze/analyze-stream: контекст → санитайзер → run."""
    org = await _org(session)
    if not body.user_prompt:
        raise HTTPException(422, "user_prompt обязателен (выберите пресет или напишите задание)")
    api_key = body.api_key or (org.settings or {}).get("llm_api_key")
    if not api_key:
        raise HTTPException(422, "нет API-ключа: укажите в запросе или сохраните в настройках организации")

    try:
        bundle = await build_context(
            session, org, mode=body.mode,
            date_from=body.date_from, date_to=body.date_to, days=body.days,
            agent_user_id=body.agent_user_id, agent_name=body.agent_name,
            risk_band=body.risk_band, score_max=body.score_max,
            direction=body.direction, min_duration_sec=body.min_duration_sec,
            objection_type=body.objection_type, call_ids=body.call_ids,
            limit_calls=body.limit_calls,
            max_context_tokens=body.max_context_tokens,
            smart_compress=body.smart_compress,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    apply_pii(bundle, body.pii)
    alias_map = (bundle.stats or {}).get("alias_map", {})

    run = LLMAnalysisRun(
        org_id=org.id,
        author_id=user.user_id,
        mode=body.mode,
        provider=body.provider,
        model_id=body.model,
        filter_spec={
            "date_from": body.date_from, "date_to": body.date_to, "days": body.days,
            "risk_band": body.risk_band, "score_max": body.score_max,
            "limit_calls": body.limit_calls, "agent_user_id": body.agent_user_id,
        },
        pii_config={
            "config": body.pii.model_dump(),
            "stats": _stats_out(bundle.stats) if bundle.stats else {},
        },
        prompt_text=body.user_prompt,
        calls_count=bundle.calls_count,
        call_ids=[str(x) for x in _bundle_call_ids(bundle)],
        status="running",
    )
    session.add(run)
    await session.flush()
    return org, bundle, run, api_key, alias_map


@router.post("/ai/analyze")
async def analyze(body: AIAnalyzeRequest, request: Request, session: SessionDep, user: RequireAnalyst) -> JSONResponse:
    """Полный цикл: контекст → санитайзер ПДн → LLM → llm_analysis_runs + аудит."""
    org, bundle, run, api_key, alias_map = await _prepare_analyze(body, session, user)

    user_content = f"{body.user_prompt}\n\n--- Данные из «Полилога» (режим {bundle.mode}) ---\n\n{bundle.markdown}"
    try:
        result = await llm_client.chat_completion(
            base_url=body.base_url,
            api_key=api_key,
            model=body.model,
            system_prompt=body.system_prompt or DEFAULT_SYSTEM_PROMPT,
            user_prompt=user_content,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            transport=getattr(request.app.state, "llm_transport", None),
        )
    except llm_client.LLMError as e:
        run.status = "failed"
        run.error_message = str(e)[:500]
        session.add(
            AuditLog(org_id=org.id, actor_id=user.user_id, action="llm_analyze",
                     resource_type="llm_run", resource_id=str(run.id),
                     details={"status": "failed", "error": str(e)[:200]}))
        await session.commit()
        raise HTTPException(502, f"ошибка LLM-эндпоинта: {e}") from e

    run.status = "done"
    run.result_markdown = result["text"]
    run.token_usage = result.get("usage") or None
    session.add(
        AuditLog(org_id=org.id, actor_id=user.user_id, action="llm_analyze",
                 resource_type="llm_run", resource_id=str(run.id),
                 details={"model": body.model, "calls": bundle.calls_count,
                          "usage": result.get("usage") or {}}))
    await session.commit()
    return JSONResponse({
        "run_id": str(run.id),
        "result_markdown": result["text"],
        "pii_stats": _stats_out(bundle.stats) if bundle.stats else {},
        "alias_map": alias_map,
        "token_usage": result.get("usage") or {},
        "calls_count": bundle.calls_count,
    })


@router.post("/ai/analyze/stream")
async def analyze_stream(
    body: AIAnalyzeRequest, request: Request, session: SessionDep, user: RequireAnalyst,
) -> StreamingResponse:
    """SSE-стриминг ИИ-анализа (DEF-03, ТЗ v4.0 §8.1): чанки `meta` (статистика
    ПДн и объём выборки до вызова LLM), `reasoning` (рассуждения reasoning-
    моделей), `content` (текст отчёта), `done` (run_id, usage), `error`."""
    org, bundle, run, api_key, alias_map = await _prepare_analyze(body, session, user)
    await session.commit()  # фиксируем run до стрима

    user_content = f"{body.user_prompt}\n\n--- Данные из «Полилога» (режим {bundle.mode}) ---\n\n{bundle.markdown}"

    async def gen():
        yield (
            "event: meta\ndata: "
            + json.dumps(
                {
                    "run_id": str(run.id),
                    "mode": bundle.mode,
                    "calls_count": bundle.calls_count,
                    "estimated_tokens": bundle.estimated_tokens,
                    "pii_stats": _stats_out(bundle.stats) if bundle.stats else {},
                    "alias_map": alias_map,
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        parts: list[str] = []
        usage: dict = {}
        try:
            async for chunk in llm_client.chat_completion_stream(
                base_url=body.base_url,
                api_key=api_key,
                model=body.model,
                system_prompt=body.system_prompt or DEFAULT_SYSTEM_PROMPT,
                user_prompt=user_content,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                transport=getattr(request.app.state, "llm_transport", None),
            ):
                if chunk.get("type") == "usage":
                    usage = chunk.get("usage") or {}
                    continue
                parts.append(chunk["delta"])
                yield (
                    f"event: {chunk['type']}\ndata: "
                    + json.dumps({"delta": chunk["delta"]}, ensure_ascii=False)
                    + "\n\n"
                )
        except llm_client.LLMError as e:
            run.status = "failed"
            run.error_message = str(e)[:500]
            session.add(
                AuditLog(org_id=org.id, actor_id=user.user_id, action="llm_analyze",
                         resource_type="llm_run", resource_id=str(run.id),
                         details={"status": "failed", "error": str(e)[:200]}))
            await session.commit()
            yield "event: error\ndata: " + json.dumps({"message": str(e)}, ensure_ascii=False) + "\n\n"
            return
        run.status = "done"
        run.result_markdown = "".join(parts)
        run.token_usage = usage or None
        session.add(
            AuditLog(org_id=org.id, actor_id=user.user_id, action="llm_analyze",
                     resource_type="llm_run", resource_id=str(run.id),
                     details={"model": body.model, "calls": bundle.calls_count,
                              "stream": True, "usage": usage}))
        await session.commit()
        yield (
            "event: done\ndata: "
            + json.dumps(
                {"run_id": str(run.id), "token_usage": usage, "calls_count": bundle.calls_count},
                ensure_ascii=False,
            )
            + "\n\n"
        )

    return StreamingResponse(gen(), media_type="text/event-stream")


def _bundle_call_ids(bundle) -> list[str]:
    """Реальные UUID звонков пакета (из alias_map до обратной подмены)."""
    out: list[str] = []
    for alias, real in ((bundle.stats or {}).get("alias_map", {})).items():
        if alias.startswith("[CALL_#"):
            out.append(real)
    return out


@router.get("/ai/models")
async def models(
    session: SessionDep,
    user: RequireAnalyst,
    base_url: str = Query(default="https://openrouter.ai/api/v1"),
    api_key: str | None = Query(default=None),
) -> dict:
    org = await _org(session)
    key = api_key or (org.settings or {}).get("llm_api_key")
    if not key:
        raise HTTPException(422, "нет API-ключа: передайте api_key или сохраните в настройках организации")
    try:
        items = await llm_client.list_models(base_url=base_url, api_key=key)
    except llm_client.LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {"items": items}


@router.get("/ai/runs")
async def runs_list(session: SessionDep, user: RequireAnalyst, limit: int = Query(default=20, le=100)) -> dict:
    org = await _org(session)
    rows = (
        (
            await session.execute(
                select(LLMAnalysisRun)
                .where(LLMAnalysisRun.org_id == org.id)
                .order_by(LLMAnalysisRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "mode": r.mode,
                "provider": r.provider,
                "model_id": r.model_id,
                "calls_count": r.calls_count,
                "status": r.status,
                "error_message": r.error_message,
                "prompt_text": (r.prompt_text or "")[:200],
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/ai/runs/{run_id}")
async def run_detail(run_id: uuid.UUID, session: SessionDep, user: RequireAnalyst) -> dict:
    org = await _org(session)
    run = await session.get(LLMAnalysisRun, run_id)
    if run is None or run.org_id != org.id:
        raise HTTPException(404, "разбор не найден")
    return {
        "id": str(run.id),
        "mode": run.mode,
        "provider": run.provider,
        "model_id": run.model_id,
        "filter_spec": run.filter_spec,
        "pii_config": run.pii_config,
        "prompt_text": run.prompt_text,
        "calls_count": run.calls_count,
        "call_ids": run.call_ids or [],
        "result_markdown": run.result_markdown,
        "token_usage": run.token_usage,
        "status": run.status,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/ai/mcp-config")
async def mcp_config(
    request: Request,
    session: SessionDep,
    user: RequireAnalyst,
    sanitize_pii: bool = Query(default=True),
) -> dict:
    """Готовые сниппеты подключения MCP-сервера из агентских харнесов
    (ТЗ v3.0 §4.4, вкладка Б). Токен в конфигах — плейсхолдер, не секрет."""
    host = request.headers.get("host") or "localhost:8000"
    scheme = "http"
    base = f"{scheme}://{host}/api/v1/mcp"
    flag = "--sanitize-pii" if sanitize_pii else ""
    tools_table = [{"name": t["name"], "description": t["description"]} for t in TOOLS]
    return {
        "tools": tools_table,
        "starter_prompt": (
            "Используй MCP-инструмент polylog_get_problematic_calls за последние 14 дней, "
            "проанализируй причины отказов и составь таблицу ошибок менеджеров."
        ),
        "harnesses": {
            "claude_code": {
                "title": "Claude Code",
                "cli_command": f"claude mcp add polylog-analytics -- python -m polylog.mcp {flag}".strip(),
                "mcp_json": {
                    "mcpServers": {
                        "polylog-analytics": {
                            "command": "python",
                            "args": ["-m", "polylog.mcp"] + ([flag] if flag else []),
                            "env": {"POLYLOG_DATABASE_URL": "postgresql+psycopg://polylog:PASSWORD@localhost:5432/polylog"},
                        }
                    }
                },
            },
            "claude_code_http": {
                "title": "Claude Code (HTTP/SSE, другая машина)",
                "mcp_json": {
                    "mcpServers": {
                        "polylog": {
                            "type": "sse",
                            "url": (
                                f"{base}/sse?api_key=YOUR_API_KEY"
                                f"&sanitize_pii={'true' if sanitize_pii else 'false'}"
                            ),
                        }
                    }
                },
            },
            "codex": {
                "title": "OpenAI Codex CLI",
                "config_toml": (
                    "[mcp_servers.polylog-analytics]\n"
                    "command = \"python\"\n"
                    "args = [\"-m\", \"polylog.mcp\""
                    + (f", \"{flag}\"" if flag else "")
                    + "]\n\n"
                    f"# HTTP-вариант: url = \"{base}/sse?api_key=YOUR_API_KEY\""
                ),
            },
            "zcode": {
                "title": "ZCode",
                "mcp_json": {
                    "mcpServers": {
                        "polylog-analytics": {
                            "command": "python",
                            "args": ["-m", "polylog.mcp"] + ([flag] if flag else []),
                            "env": {"POLYLOG_DATABASE_URL": "postgresql+psycopg://polylog:PASSWORD@localhost:5432/polylog"},
                        }
                    }
                },
            },
            "cursor": {
                "title": "Cursor / Windsurf",
                "mcp_json": {
                    "mcpServers": {
                        "polylog-analytics": {
                            "command": "python",
                            "args": ["-m", "polylog.mcp"] + ([flag] if flag else []),
                        }
                    }
                },
            },
            "claude_desktop": {
                "title": "Claude Desktop",
                "config_json": {
                    "mcpServers": {
                        "polylog-analytics": {
                            "command": "python",
                            "args": ["-m", "polylog.mcp"] + ([flag] if flag else []),
                            "env": {"POLYLOG_DATABASE_URL": "postgresql+psycopg://polylog:PASSWORD@localhost:5432/polylog"},
                        }
                    }
                },
            },
        },
    }


# ── MCP HTTP-транспорт ──


@router.post("/mcp/rpc")
async def mcp_rpc(request: Request, payload: dict, session: SessionDep, user: AuthDep) -> JSONResponse:
    """Одиночный JSON-RPC 2.0 запрос к MCP-серверу (initialize/tools/list/tools/call)."""
    org = await _org(session)
    registry = getattr(request.app.state, "mcp_registry", None)
    if registry is None:
        registry = {}
        request.app.state.mcp_registry = registry
    resp = await handle_rpc(payload, session, org, registry)
    if resp is None:  # уведомление без id — ответа нет
        return Response(status_code=204)
    return JSONResponse(resp)


@router.get("/mcp/sse")
async def mcp_sse(request: Request, user: AuthDep) -> StreamingResponse:
    """SSE-транспорт MCP (ТЗ v3.0 §4.5): поток endpoint-события + ответов на
    запросы, отправленные в /api/v1/mcp/messages?session_id=...
    Авторизация — Bearer или ?api_key= (SSE-клиент не умеет заголовки)."""
    sessions = getattr(request.app.state, "mcp_sse_sessions", None)
    if sessions is None:
        sessions = {}
        request.app.state.mcp_sse_sessions = sessions
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    sessions[session_id] = queue

    async def stream():
        try:
            yield f"event: endpoint\ndata: /api/v1/mcp/messages?session_id={session_id}\n\n"
            while True:
                try:
                    resp = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {json.dumps(resp, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            sessions.pop(session_id, None)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/mcp/messages")
async def mcp_messages(
    request: Request,
    payload: dict,
    session: SessionDep,
    user: AuthDep,
    session_id: str = Query(default=""),
) -> JSONResponse:
    """POST-половина SSE-транспорта: запрос в очередь выбранного SSE-подключения."""
    sessions = getattr(request.app.state, "mcp_sse_sessions", {})
    queue = sessions.get(session_id)
    if queue is None:
        raise HTTPException(404, "SSE-сессия не найдена: откройте GET /api/v1/mcp/sse")
    org = await _org(session)
    registry = getattr(request.app.state, "mcp_registry", None)
    if registry is None:
        registry = {}
        request.app.state.mcp_registry = registry
    resp = await handle_rpc(payload, session, org, registry)
    if resp is not None:
        await queue.put(resp)
        return JSONResponse({"accepted": True})
    return JSONResponse(status_code=202, content={"accepted": True, "notification": True})
