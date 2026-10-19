"""Periodic-джобы (doc 08 §1, doc 09 §8): переоценка рисков, повторы,
ночной S6-регресс ASR. Регистрируются в том же App, что и воркер;
расписание — cron procrastinate. Включение: env POLYLOG_PERIODIC=1
(воркер с periodic-деферрером). Ночной S6: POLYLOG_NIGHTLY_S6=1
(требует модели; WER пишется в лог и data/datasets/golden/nightly_wer.json).

Риск-джоба пересчитывает scorecard всех контактов и складывает деградации
в ленту `insights` (kind=risk_account). Там же — повторяющиеся нерешённые
проблемы контакта (kind=repeat_objection, Root-Cause «Unresolved Repeat»).
Дедуп — upsert существующего new-инсайта по ключу (kind, contact, type).
"""

from __future__ import annotations

import logging

from polylog.tasks import app

log = logging.getLogger("polylog.periodic")


def _repo_root():
    """Корень монорепо (periodic.py → polylog → core → root)."""
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


async def refresh_insights(session) -> dict[str, int]:
    """Пересчёт risk_account + repeat_objection инсайтов (upsert по дедуп-ключам).
    Отдельная функция — чтобы тесты звали её на тестовой сессии без движка джобы."""
    from datetime import datetime

    from sqlalchemy import select

    from polylog.graph.service import get_default_org
    from polylog.insights.repeat import find_repeats
    from polylog.models.calls import Call, Objection
    from polylog.models.system import Insight
    from polylog.risk import risk_for_contact

    org = await get_default_org(session)
    contact_ids = (
        (
            await session.execute(
                select(Call.contact_id)
                .where(Call.org_id == org.id, Call.contact_id.is_not(None))
                .distinct()
            )
        )
        .scalars()
        .all()
    )

    # дедуп в памяти: (kind, contact_id[, type]) → существующий new-инсайт
    existing = (
        (
            await session.execute(
                select(Insight).where(
                    Insight.org_id == org.id,
                    Insight.status == "new",
                    Insight.kind.in_(["risk_account", "repeat_objection"]),
                )
            )
        )
        .scalars()
        .all()
    )

    def dedup_key(kind: str, payload: dict) -> tuple:
        key = (kind, payload.get("contact_id"))
        if kind == "repeat_objection":
            return key + (payload.get("type"),)
        return key

    by_key: dict[tuple, Insight] = {
        dedup_key(i.kind, i.payload or {}): i for i in existing
    }

    counts = {"risk_account": 0, "repeat_objection": 0}
    for cid in contact_ids:
        # риск: scorecard контакта
        risk = await risk_for_contact(session, org.id, cid)
        if risk is not None:
            payload = {
                "score": risk["score"],
                "band": risk["band"],
                "factors": risk["factors"][:3],
                "model_id": risk["model_id"],
                "contact_id": str(cid),
            }
            existing_insight = by_key.get(dedup_key("risk_account", payload))
            if existing_insight is not None:
                existing_insight.payload = payload
            else:
                session.add(
                    Insight(
                        org_id=org.id,
                        kind="risk_account",
                        severity="critical" if risk["band"] == "high" else "warning",
                        company_id=None,
                        deal_id=None,
                        agent_user_id=None,
                        payload=payload,
                        generated_by=risk["model_id"],
                        status="new",
                    )
                )
            counts["risk_account"] += 1

        # повторяющиеся нерешённые проблемы контакта
        rows = (
            (
                await session.execute(
                    select(Call.started_at, Objection.type, Objection.response_status)
                    .outerjoin(Objection, Objection.call_id == Call.id)
                    .where(Call.contact_id == cid)
                    .order_by(Call.started_at)
                )
            )
            .all()
        )
        by_call: dict[datetime, list[tuple[str, str | None]]] = {}
        for started, ty, status in rows:
            if ty is not None:
                by_call.setdefault(started, []).append((ty, status))
        repeats = find_repeats(list(by_call.items()))
        for r in repeats:
            payload = {
                "contact_id": str(cid),
                "type": r["type"],
                "calls": r["calls"],
                "last_status": r["last_status"],
                "last_at": r["last_at"],
            }
            existing_insight = by_key.get(dedup_key("repeat_objection", payload))
            if existing_insight is not None:
                existing_insight.payload = payload
            else:
                session.add(
                    Insight(
                        org_id=org.id,
                        kind="repeat_objection",
                        severity="warning",
                        company_id=None,
                        deal_id=None,
                        agent_user_id=None,
                        contact_id=cid,
                        payload=payload,
                        generated_by="repeat@0.1.0",
                        status="new",
                    )
                )
            counts["repeat_objection"] += 1

    await session.commit()
    return counts


@app.periodic(cron="0 6 * * *", periodic_id="risk-insights-daily")
@app.task(name="recompute_risk_insights", queue="pipeline")
async def recompute_risk_insights(timestamp: int | None = None) -> None:
    """Ежедневно 06:00: риски + повторы всех контактов → лента insights (upsert)."""
    from polylog.config import get_settings
    from polylog.db import make_engine, make_sessionmaker

    settings = get_settings()
    engine = make_engine(settings.database_url)
    sm = make_sessionmaker(engine)
    async with sm() as session:
        counts = await refresh_insights(session)
    await engine.dispose()
    log.info(
        "periodic: инсайты обновлены: risk_account=%s repeat_objection=%s",
        counts["risk_account"], counts["repeat_objection"],
    )


async def run_nightly_s6() -> dict[str, object]:
    """Ночной S6-регресс (S6, doc 02 §8): WER golden-эталона на gigaam.
    Выключено без POLYLOG_NIGHTLY_S6=1. Отдельная функция — тестируемо без
    procrastinate; результат в лог и nightly_wer.json рядом с golden."""
    import os

    if os.environ.get("POLYLOG_NIGHTLY_S6") != "1":
        log.info("nightly S6 выключен (POLYLOG_NIGHTLY_S6 != 1)")
        return {"status": "skipped"}

    import asyncio
    import json
    import sys
    from datetime import UTC, datetime

    bench = _repo_root() / "tools" / "datasets" / "benchmark_asr.py"
    golden = _repo_root() / "data" / "datasets" / "golden"
    if not bench.is_file() or not golden.is_dir():
        log.warning("nightly S6: нет %s или %s", bench, golden)
        return {"status": "missing_inputs"}

    out_json = golden / "nightly_wer.json"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(bench),
        "--audio-dir", str(golden),
        "--backend", "gigaam-v3-e2e-rnnt",
        "--out", str(out_json),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    wer = None
    if out_json.is_file():
        try:
            wer = json.loads(out_json.read_text(encoding="utf-8")).get("wer")
        except Exception:  # noqa: BLE001 — кривой отчёт не ломает джобу
            pass
    log.info(
        "nightly S6: rc=%s wer=%s\n%s",
        proc.returncode, wer, (stdout or b"")[-1500:].decode("utf-8", errors="replace"),
    )
    return {
        "status": "ok",
        "returncode": proc.returncode,
        "wer": wer,
        "finished_at": datetime.now(UTC).isoformat(),
    }


@app.periodic(cron="0 3 * * *", periodic_id="nightly-s6")
@app.task(name="nightly_regression_s6", queue="pipeline")
async def nightly_regression_s6(timestamp: int | None = None) -> None:
    """Ежедневно 03:00: регресс WER на golden (вкл. POLYLOG_NIGHTLY_S6=1)."""
    await run_nightly_s6()
