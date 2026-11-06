"""Точка входа MCP stdio (ТЗ v3.0 §4.5): python -m polylog.mcp
Каждая строка stdin — JSON-RPC 2.0 запрос, ответ — строка stdout.
Реестр алиасов [CALL_#N] живёт в процессе, поэтому агент (Claude Code,
Codex, ZCode) может сослаться на звонок из предыдущего вызова тулза."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from polylog.mcp.server import handle_rpc


def _build_sessionmaker(database_url: str | None):
    from polylog.db import make_engine, make_sessionmaker

    url = database_url or _env_database_url()
    engine = make_engine(url)
    return make_sessionmaker(engine), engine


def _env_database_url() -> str:
    import os

    from polylog.config import get_settings

    return os.environ.get("POLYLOG_DATABASE_URL") or get_settings().database_url


async def _amain(args: argparse.Namespace) -> int:
    from polylog.graph.service import get_default_org

    sessionmaker, engine = _build_sessionmaker(args.database_url)
    registry: dict[str, str] = {}
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        try:
            async with sessionmaker() as session:
                org = await get_default_org(session)
                resp = await handle_rpc(payload, session, org, registry)
        except Exception as e:  # noqa: BLE001 — ответ-ошибка вместо падения процесса
            resp = {
                "jsonrpc": "2.0",
                "id": payload.get("id") if isinstance(payload, dict) else None,
                "error": {"code": -32603, "message": str(e)[:300]},
            }
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="polylog-mcp",
        description="MCP-сервер «Полилога» (stdio): 5 тулзов речевой аналитики с очисткой ПДн",
    )
    parser.add_argument("--db", dest="database_url", default=None, help="URL БД (иначе POLYLOG_DATABASE_URL)")
    parser.add_argument(
        "--sanitize-pii", dest="sanitize_pii", action="store_true", default=True,
        help="Очищать ПДн по умолчанию (переопределяется аргументом тулза)",
    )
    ns = parser.parse_args(argv)
    try:
        return asyncio.run(_amain(ns))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
