"""Сборка контекста для LLM и MCP (ТЗ v3.0 §4.3): три режима выборки —
rubert_scores (скоринг и чек-листы), problematic_calls (риски и проблемные),
transcripts_range (транскрипты за период). Собирает структурированный пакет +
Markdown и применяет PiiSanitizer (apply_pii) перед отправкой наружу.

Без ленивых загрузок: дочерние таблицы — selectin-relationship модели Call или
явные select() по id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.insights.repeat import find_repeats
from polylog.models.calls import Call, Objection, Score, Signal, Violation
from polylog.models.graph import Contact
from polylog.models.system import User
from polylog.pii.sanitizer import (
    PiiSanitizer,
    PiiSanitizerConfig,
    estimate_tokens,
)
from polylog.risk.batch import compute_org_risks_batch

MODES = ("rubert_scores", "problematic_calls", "transcripts_range")

ROLE_RU = {"agent": "Менеджер", "client": "Клиент"}


class ContextBundle:
    """Результат сборки: markdown + структурный пакет + статистика ПДн."""

    def __init__(
        self,
        mode: str,
        markdown: str,
        structured: dict[str, Any],
        calls_count: int,
        stats: dict[str, Any] | None = None,
    ):
        self.mode = mode
        self.markdown = markdown
        self.structured = structured
        self.calls_count = calls_count
        self.stats = stats
        self.estimated_tokens = estimate_tokens(markdown)


# ── служебные ──


def _parse_dt(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if end_of_day and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def _period_bounds(days: int | None, date_from: str | None, date_to: str | None):
    now = datetime.now(UTC)
    dt_from = _parse_dt(date_from) or (now - timedelta(days=days or 30))
    dt_to = _parse_dt(date_to, end_of_day=True) or now
    return dt_from, dt_to


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    total = int(ms / 1000)
    return f"{total // 60:02d}:{total % 60:02d}"


def _sentiment_of(metrics: dict | None) -> float | None:
    cs = (metrics or {}).get("client_sentiment")
    return float(cs["score"]) if cs and "score" in cs else None


def _agent_ext_of(call: Call) -> str | None:
    if call.direction == "outbound" and call.phone_from and call.phone_from.isdigit() and len(call.phone_from) <= 6:
        return call.phone_from
    if call.direction == "inbound" and call.phone_to and call.phone_to.isdigit() and len(call.phone_to) <= 6:
        return call.phone_to
    return None


async def _resolve_agents(session: AsyncSession, org_id: uuid.UUID, agent_name: str | None) -> list[uuid.UUID]:
    """display_name/email агента → список id (фильтр MCP-тулзов)."""
    if not agent_name:
        return []
    rows = (
        (
            await session.execute(
                select(User).where(
                    User.org_id == org_id,
                    User.display_name.ilike(f"%{agent_name}%") | User.email.ilike(f"%{agent_name}%"),
                )
            )
        )
        .scalars()
        .all()
    )
    return [u.id for u in rows]


async def _fetch_calls(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    dt_from: datetime,
    dt_to: datetime,
    agent_user_id: uuid.UUID | None = None,
    agent_ids: list[uuid.UUID] | None = None,
    direction: str | None = None,
    min_duration: int | None = None,
    call_ids: list[uuid.UUID] | None = None,
    limit: int = 30,
) -> list[Call]:
    conds: list[Any] = [
        Call.org_id == org_id,
        Call.state == "done",
        Call.started_at >= dt_from,
        Call.started_at <= dt_to,
    ]
    if agent_user_id:
        conds.append(Call.agent_user_id == agent_user_id)
    elif agent_ids:
        conds.append(Call.agent_user_id.in_(agent_ids))
    if direction in ("inbound", "outbound", "internal"):
        conds.append(Call.direction == direction)
    if min_duration:
        conds.append(Call.duration_sec >= min_duration)
    if call_ids:
        conds.append(Call.id.in_(call_ids))
    rows = (
        (
            await session.execute(
                select(Call).where(*conds).order_by(Call.started_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _scores_map(session: AsyncSession, call_ids: list[uuid.UUID]) -> dict[uuid.UUID, Score]:
    if not call_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(Score)
                .where(Score.call_id.in_(call_ids))
                .order_by(Score.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out: dict[uuid.UUID, Score] = {}
    for sc in rows:  # первые по дате desc = последние
        out.setdefault(sc.call_id, sc)
    return out


def _base_entry(call: Call, score: Score | None, agent_name: str | None, contact_name: str | None) -> dict[str, Any]:
    return {
        "call_id": str(call.id),
        "external_id": call.external_id,
        "direction": call.direction,
        "started_at": call.started_at.isoformat(),
        "duration_sec": call.duration_sec,
        "agent_ext": _agent_ext_of(call),
        "agent_name": agent_name,
        "contact_name": contact_name,
        "phone_from": call.phone_from,
        "phone_to": call.phone_to,
        "contact_id": str(call.contact_id) if call.contact_id else None,
        "deal_id": str(call.deal_id) if call.deal_id else None,
        "score_total": round(score.total, 1) if score else None,
        "sentiment": _sentiment_of(call.metrics.metrics if call.metrics else None),
    }


# ── режим 1: rubert_scores ──


async def _mode_rubert_scores(session, org, req) -> tuple[str, dict, list[Call]]:
    dt_from, dt_to = _period_bounds(req.get("days", 30), req.get("date_from"), req.get("date_to"))
    agent_ids = await _resolve_agents(session, org.id, req.get("agent_name"))
    calls = await _fetch_calls(
        session,
        org.id,
        dt_from=dt_from,
        dt_to=dt_to,
        agent_user_id=req.get("agent_user_id"),
        agent_ids=agent_ids,
        call_ids=req.get("call_ids"),
        limit=req.get("limit_calls", 30),
    )
    scores = await _scores_map(session, [c.id for c in calls])
    score_max = req.get("score_max")
    if score_max is not None:
        calls = [c for c in calls if scores.get(c.id) and scores[c.id].total <= float(score_max)]

    agents = (
        (await session.execute(select(User).where(User.org_id == org.id))).scalars().all()
    )
    agent_names = {u.id: (u.display_name or u.email) for u in agents}
    contact_ids = [c.contact_id for c in calls if c.contact_id]
    contacts = (
        (await session.execute(select(Contact).where(Contact.id.in_(contact_ids))))
        .scalars()
        .all()
    )
    contact_names = {c.id: c.display_name for c in contacts}

    call_ids_list = [c.id for c in calls]
    objections = (
        (await session.execute(select(Objection).where(Objection.call_id.in_(call_ids_list))))
        .scalars()
        .all()
    )
    violations = (
        (await session.execute(select(Violation).where(Violation.call_id.in_(call_ids_list))))
        .scalars()
        .all()
    )
    objections_by_call: dict[uuid.UUID, list[Objection]] = {}
    for o in objections:
        objections_by_call.setdefault(o.call_id, []).append(o)
    violations_by_call: dict[uuid.UUID, list[Violation]] = {}
    for v in violations:
        violations_by_call.setdefault(v.call_id, []).append(v)

    lines: list[str] = [
        f"# Скоринг звонков и чек-листы (период {dt_from.date()} — {dt_to.date()})",
        "",
    ]
    entries: list[dict[str, Any]] = []
    for call in calls:
        sc = scores.get(call.id)
        metrics = call.metrics.metrics if call.metrics else {}
        nli = (metrics or {}).get("nli") or {}
        agent_name = agent_names.get(call.agent_user_id) if call.agent_user_id else None
        contact_name = contact_names.get(call.contact_id) if call.contact_id else None
        entry = _base_entry(call, sc, agent_name, contact_name)
        entry["nli"] = {
            "answered": nli.get("answered"),
            "ignored": nli.get("ignored"),
            "ratio": nli.get("nli_answered_ratio"),
        }
        entry["objections"] = [
            {
                "type": o.type,
                "status": o.response_status,
                "quote": o.span_text,
                "response": o.response_span,
            }
            for o in objections_by_call.get(call.id, [])
        ]
        entry["violations"] = [
            {"kind": v.kind, "quote": v.span_text} for v in violations_by_call.get(call.id, [])
        ]
        if sc:
            entry["rubric_items"] = [
                {
                    "item_id": it.get("item_id"),
                    "title": it.get("title"),
                    "score": it.get("score"),
                    "weight": it.get("weight"),
                    "explanation": it.get("explanation"),
                    "evidence": [ev.get("span") for ev in (it.get("evidence") or [])],
                }
                for it in (sc.items or [])
            ]
        entries.append(entry)

        # UUID в заголовке → после apply_pii превращается в кликабельный [CALL_#N]
        lines.append(f"## Звонок {call.id} {call.started_at.strftime('%Y-%m-%d %H:%M')}, {call.direction}")
        meta = []
        if agent_name:
            meta.append(f"менеджер: {agent_name}")
        if contact_name:
            meta.append(f"клиент: {contact_name}")
        if meta:
            lines.append("(" + ", ".join(meta) + ")")
        lines.append(f"Балл: {entry['score_total'] if entry['score_total'] is not None else '—'}")
        for it in entry.get("rubric_items", []):
            lines.append(
                f"- {it['title']}: {it['score']}/{it['weight']} — {it.get('explanation') or ''}"
                + (f" Цитаты: {'; '.join(it['evidence'])}" if it["evidence"] else "")
            )
        if entry["nli"].get("ratio") is not None:
            lines.append(
                f"- NLI: отвечено {entry['nli']['answered']}, без ответа {entry['nli']['ignored']} "
                f"(доля ответов {entry['nli']['ratio']})"
            )
        for o in entry["objections"]:
            line = f"- Возражение «{o['type']}» ({o['status'] or 'статус неизвестен'}): «{o['quote']}»"
            if o["response"]:
                line += f" → ответ: «{o['response']}»"
            lines.append(line)
        for v in entry["violations"]:
            lines.append(f"- Нарушение {v['kind']}: «{v['quote']}»")
        lines.append("")
    return "\n".join(lines), {"mode": "rubert_scores", "calls": entries}, calls


# ── режим 2: problematic_calls ──


async def _mode_problematic(session, org, req) -> tuple[str, dict, list[Call]]:
    dt_from, dt_to = _period_bounds(req.get("days", 30), req.get("date_from"), req.get("date_to"))
    band = (req.get("risk_band") or "high").lower()
    max_score = req.get("score_max")
    limit = req.get("limit_calls", 30)

    risks = await compute_org_risks_batch(session, org.id)
    if band == "high":
        risky = {cid: r for cid, r in risks.items() if r.get("band") == "high"}
    else:  # medium / medium_plus — средний и выше
        risky = {cid: r for cid, r in risks.items() if r.get("band") in ("high", "medium")}

    agents = (
        (await session.execute(select(User).where(User.org_id == org.id))).scalars().all()
    )
    agent_names = {u.id: (u.display_name or u.email) for u in agents}

    dossier_contacts = list(risky.keys())[:limit]
    entries: list[dict[str, Any]] = []
    lines: list[str] = [
        f"# Проблемные звонки и риски (период {dt_from.date()} — {dt_to.date()})",
        "",
    ]
    seen_call_ids: list[Call] = []

    for cid in dossier_contacts:
        risk = risky[cid]
        feats = risk.get("features", {})
        call_rows = (
            (
                await session.execute(
                    select(Call)
                    .where(Call.org_id == org.id, Call.contact_id == cid)
                    .order_by(Call.started_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        call_objections: list[tuple[datetime, list[tuple[str, str | None]]]] = []
        obj_rows = (
            (
                await session.execute(
                    select(Objection).where(
                        Objection.call_id.in_([c.id for c in call_rows])
                    )
                )
            )
            .scalars()
            .all()
        )
        obj_by_call: dict[uuid.UUID, list[Objection]] = {}
        started_by_call = {c.id: c.started_at for c in call_rows}
        for o in obj_rows:
            obj_by_call.setdefault(o.call_id, []).append(o)
        for c in call_rows:
            pairs = [(o.type, o.response_status) for o in obj_by_call.get(c.id, [])]
            if pairs:
                call_objections.append((started_by_call[c.id], pairs))
        repeats = find_repeats(call_objections)
        contact = await session.get(Contact, cid) if cid else None

        entry = {
            "contact_id": str(cid),
            "contact_name": contact.display_name if contact else None,
            "risk_score": risk.get("score"),
            "risk_band": risk.get("band"),
            "factors": feats,
            "repeats": repeats,
            "calls": [
                _base_entry(c, None, agent_names.get(c.agent_user_id) if c.agent_user_id else None, None)
                for c in call_rows[:5]
            ],
            "objections": [
                {
                    "call_id": str(o.call_id),
                    "type": o.type,
                    "status": o.response_status,
                    "quote": o.span_text,
                    "response": o.response_span,
                }
                for o in obj_rows
            ],
        }
        entries.append(entry)
        seen_call_ids.extend(call_rows[:5])

        lines.append(
            f"## Клиент {contact.display_name if contact else '—'} — риск {risk.get('score')} ({risk.get('band')})"
        )
        lines.append(
            f"- Факторы: дней тишины {feats.get('days_silence')}, звонков {feats.get('calls_total')}, "
            f"средний балл {feats.get('avg_score')}, неотработанных возражений {feats.get('objections_unhandled')}"
        )
        for rep in repeats:
            lines.append(
                f"- Повторяющееся возражение «{rep['type']}»: {rep['calls']} звонка, "
                f"последняя отработка — {rep['last_status']}"
            )
        for sub in entry["calls"]:
            lines.append(
                f"- Звонок {sub['call_id']} {sub['started_at'][:10]}, "
                f"{sub['direction']}, {sub['duration_sec'] or 0} сек"
            )
        for o in entry["objections"][:6]:
            lines.append(f"- Возражение «{o['type']}» ({o['status'] or '?'}): «{o['quote']}»")
        lines.append("")

    # Проваленные звонки: низкий скор или негативный сентимент
    score_max = 50.0 if max_score is None else float(max_score)
    low_calls = await _fetch_calls(
        session, org.id, dt_from=dt_from, dt_to=dt_to, limit=limit, min_duration=10
    )
    scores = await _scores_map(session, [c.id for c in low_calls])
    failed_entries: list[dict[str, Any]] = []
    for c in low_calls:
        sc = scores.get(c.id)
        sent = _sentiment_of(c.metrics.metrics if c.metrics else None)
        if (sc and sc.total < score_max) or (sent is not None and sent < -0.2):
            agent_name = agent_names.get(c.agent_user_id) if c.agent_user_id else None
            entry = _base_entry(c, sc, agent_name, None)
            entry["risk_score"] = None
            failed_entries.append(entry)
            seen_call_ids.append(c)
            score_str = entry["score_total"] if entry["score_total"] is not None else "—"
            sent_str = sent if sent is not None else "—"
            lines.append(
                f"## Проваленный звонок {c.id} {c.started_at.strftime('%Y-%m-%d %H:%M')}"
                f" — балл {score_str}, тональность {sent_str}"
            )
            lines.append("")

    structured = {"mode": "problematic_calls", "clients": entries, "failed_calls": failed_entries}
    return "\n".join(lines), structured, seen_call_ids[:limit]


# ── режим 3: transcripts_range ──


def _compress_dialogue(segments: list[dict], key_texts: list[str]) -> tuple[list[dict], int]:
    """smart_compress (DEF-03): окно ключевых реплик — первые 3, последние 3,
    реплики с вопросами «?», возражениями/нарушениями (key_texts) и по одной
    соседней реплике контекста. Возвращает (реплики, число пропущенных)."""
    if len(segments) <= 8:
        return segments, 0
    key_lower = {t.lower() for t in key_texts if t}
    keep: set[int] = set()
    for i, s in enumerate(segments):
        if i < 3 or i >= len(segments) - 3:
            keep.add(i)
        elif "?" in (s.get("text") or ""):
            keep.add(i)
        elif any(k and k in (s.get("text") or "").lower() for k in key_lower):
            keep.add(i)
    # ±1 соседняя реплика вокруг ключевых
    for i in list(keep):
        keep.add(max(0, i - 1))
        keep.add(min(len(segments) - 1, i + 1))
    kept = [s for i, s in enumerate(segments) if i in keep]
    return kept, len(segments) - len(kept)


async def _mode_transcripts(session, org, req) -> tuple[str, dict, list[Call]]:
    dt_from, dt_to = _period_bounds(req.get("days", 30), req.get("date_from"), req.get("date_to"))
    agent_ids = await _resolve_agents(session, org.id, req.get("agent_name"))
    calls = await _fetch_calls(
        session,
        org.id,
        dt_from=dt_from,
        dt_to=dt_to,
        agent_ids=agent_ids,
        direction=req.get("direction"),
        min_duration=req.get("min_duration_sec"),
        call_ids=req.get("call_ids"),
        limit=req.get("limit_calls", 50),
    )
    scores = await _scores_map(session, [c.id for c in calls])
    agents = (
        (await session.execute(select(User).where(User.org_id == org.id))).scalars().all()
    )
    agent_names = {u.id: (u.display_name or u.email) for u in agents}
    objection_type = req.get("objection_type")
    obj_rows = (
        (
            await session.execute(
                select(Objection).where(Objection.call_id.in_([c.id for c in calls]))
            )
        )
        .scalars()
        .all()
    )
    if objection_type:
        obj_rows = [o for o in obj_rows if o.type == objection_type]
    obj_by_call: dict[uuid.UUID, list[Objection]] = {}
    for o in obj_rows:
        obj_by_call.setdefault(o.call_id, []).append(o)

    budget = req.get("max_context_tokens")
    smart = req.get("smart_compress", True)
    size = 200  # заголовок
    lines: list[str] = [
        f"# Транскрипты звонков за период {dt_from.date()} — {dt_to.date()}",
        "",
    ]
    entries: list[dict[str, Any]] = []
    for call in calls:
        sc = scores.get(call.id)
        metrics = call.metrics.metrics if call.metrics else {}
        agent_name = agent_names.get(call.agent_user_id) if call.agent_user_id else None
        entry = _base_entry(call, sc, agent_name, None)
        entry["talk_ratio"] = (metrics or {}).get("talk_ratio")
        entry["objections"] = [
            {"type": o.type, "status": o.response_status, "quote": o.span_text}
            for o in obj_by_call.get(call.id, [])
        ]
        dialogue = [
            {
                "idx": s.idx,
                "speaker": s.speaker,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
            }
            for s in call.segments
        ]
        dropped = 0
        header_len = 120 + sum(len(o["quote"]) for o in entry["objections"])
        if budget and smart and size + header_len > budget:
            break  # бюджет исчерпан — остальные звонки не включаем
        if budget and smart and size + header_len + sum(len(d["text"]) for d in dialogue) > budget:
            key_texts = [o["quote"] for o in entry["objections"]]
            dialogue, dropped = _compress_dialogue(dialogue, key_texts)
        entry["segments"] = dialogue
        entry["omitted_turns"] = dropped
        entries.append(entry)
        size += header_len + sum(len(d["text"]) for d in dialogue)

        lines.append(
            f"## Звонок {call.id} {call.started_at.strftime('%Y-%m-%d %H:%M')}, {call.direction}, "
            f"{call.duration_sec or 0} сек, балл {entry['score_total'] if entry['score_total'] is not None else '—'}"
        )
        if agent_name:
            lines.append(f"Менеджер: {agent_name}")
        if dropped:
            lines.append(f"[smart_compress: {dropped} реплик опущено — сохранены ключевые окна]")
        for d in dialogue:
            role = ROLE_RU.get(d["speaker"], d["speaker"])
            lines.append(f"[{_fmt_ms(d['start_ms'])}] {role}: {d['text']}")
        for o in entry["objections"]:
            lines.append(f"> Возражение «{o['type']}» ({o['status'] or '?'}): «{o['quote']}»")
        lines.append("")
    return "\n".join(lines), {"mode": "transcripts_range", "calls": entries}, calls


# ── публичные функции ──

_MODE_BUILDERS = {
    "rubert_scores": _mode_rubert_scores,
    "problematic_calls": _mode_problematic,
    "transcripts_range": _mode_transcripts,
}


async def build_context(
    session: AsyncSession,
    org,
    *,
    mode: str,
    date_from: str | None = None,
    date_to: str | None = None,
    days: int = 30,
    agent_user_id: str | None = None,
    agent_name: str | None = None,
    risk_band: str | None = None,
    score_max: float | None = None,
    direction: str | None = None,
    min_duration_sec: int | None = None,
    objection_type: str | None = None,
    call_ids: list[str] | None = None,
    limit_calls: int = 30,
    max_context_tokens: int = 48000,
    smart_compress: bool = True,
) -> ContextBundle:
    """Собирает контекст по режиму (без санитайзера — см. apply_pii).

    Бюджет токенов (DEF-03): в transcripts_range длинные диалоги сжимаются
    smart_compress'ом до ключевых окон; если контекст всё равно превышает
    max_context_tokens, лимит звонков урезается вдво́е до вписывания."""
    if mode not in MODES:
        raise ValueError(f"неизвестный режим: {mode}; доступно {MODES}")

    async def _build(limit: int) -> tuple[str, dict, list[Call]]:
        req: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "days": days,
            "agent_user_id": uuid.UUID(agent_user_id) if agent_user_id else None,
            "agent_name": agent_name,
            "risk_band": risk_band,
            "score_max": score_max,
            "direction": direction,
            "min_duration_sec": min_duration_sec,
            "objection_type": objection_type,
            "call_ids": [uuid.UUID(x) for x in call_ids or []],
            "limit_calls": limit,
            "max_context_tokens": max_context_tokens,
            "smart_compress": smart_compress,
        }
        return await _MODE_BUILDERS[mode](session, org, req)

    limit = max(1, limit_calls)
    for _ in range(3):
        markdown, structured, calls = await _build(limit)
        if estimate_tokens(markdown) <= max_context_tokens or limit <= 4:
            break
        limit = max(4, limit // 2)
    unique_ids = {c.id for c in calls}
    return ContextBundle(mode=mode, markdown=markdown, structured=structured, calls_count=len(unique_ids))


def apply_pii(
    bundle: ContextBundle,
    config: PiiSanitizerConfig | None = None,
) -> ContextBundle:
    """Очистка пакета и markdown через SanitizerSession (ТЗ v3.0 §8.3).

    Порядок: структурные ID → алиасы [CALL_#1]/[CONTACT_#1]; телефоны →
    [ТЕЛЕФОН_1] (один ключ с текстовыми номерами); имена → [ФИО_1] с
    последующей заменой в репликах (replace_known); затем текстовые поля и
    markdown (UUID в заголовках превращаются в [CALL_#1] через _real_index)."""
    sanitizer = PiiSanitizer(config)
    cfg = sanitizer.config
    if cfg.enabled:
        for group in ("calls", "clients", "failed_calls"):
            for entry in bundle.structured.get(group, []):
                entry["call_id"] = sanitizer.register_id("call", entry.get("call_id"))
                entry["contact_id"] = sanitizer.register_id("contact", entry.get("contact_id"))
                entry["deal_id"] = sanitizer.register_id("deal", entry.get("deal_id"))
                if entry.get("external_id"):
                    entry["external_id"] = sanitizer.register_internal_id(
                        str(entry["external_id"]), "EXT_"
                    )
                for f in ("phone_from", "phone_to"):
                    if entry.get(f):
                        entry[f] = sanitizer.register_known_phone(entry[f])
                for f in ("agent_name", "contact_name"):
                    if entry.get(f):
                        entry[f] = sanitizer.register_known_name(entry[f])
            for entry in bundle.structured.get("clients", []):
                for sub in entry.get("calls", []):
                    sub["call_id"] = sanitizer.register_id("call", sub.get("call_id"))
                    if sub.get("external_id"):
                        sub["external_id"] = sanitizer.register_internal_id(
                            str(sub["external_id"]), "EXT_"
                        )
                    for f in ("phone_from", "phone_to"):
                        if sub.get(f):
                            sub[f] = sanitizer.register_known_phone(sub[f])
                    for f in ("agent_name", "contact_name"):
                        if sub.get(f):
                            sub[f] = sanitizer.register_known_name(sub[f])
        bundle.structured = sanitizer.sanitize_obj(bundle.structured)
        bundle.markdown = sanitizer.sanitize_text(bundle.markdown)
    bundle.stats = sanitizer.summary()
    bundle.estimated_tokens = estimate_tokens(bundle.markdown)
    return bundle


# ── срезы для MCP-тулзов ──


async def call_detail_bundle(
    session: AsyncSession, org, call_id: uuid.UUID
) -> dict[str, Any] | None:
    """Полный разбор одного звонка (MCP polylog_get_call_details)."""
    call = await session.get(Call, call_id)
    if call is None or call.org_id != org.id:
        return None
    scores = await _scores_map(session, [call.id])
    sc = scores.get(call.id)
    objections = (
        (await session.execute(select(Objection).where(Objection.call_id == call.id))).scalars().all()
    )
    violations = (
        (await session.execute(select(Violation).where(Violation.call_id == call.id))).scalars().all()
    )
    signals = (
        (await session.execute(select(Signal).where(Signal.call_id == call.id))).scalars().all()
    )
    metrics = call.metrics.metrics if call.metrics else {}
    agent_name = None
    if call.agent_user_id:
        u = await session.get(User, call.agent_user_id)
        agent_name = u.display_name or u.email if u else None
    return {
        "call_id": str(call.id),
        "external_id": call.external_id,
        "direction": call.direction,
        "started_at": call.started_at.isoformat(),
        "duration_sec": call.duration_sec,
        "agent_name": agent_name,
        "phone_from": call.phone_from,
        "phone_to": call.phone_to,
        "score_total": round(sc.total, 1) if sc else None,
        "rubric_items": sc.items if sc else [],
        "nli": (metrics or {}).get("nli"),
        "talk_ratio": (metrics or {}).get("talk_ratio"),
        "sentiment": _sentiment_of(metrics),
        "objections": [
            {
                "type": o.type,
                "status": o.response_status,
                "quote": o.span_text,
                "response": o.response_span,
            }
            for o in objections
        ],
        "violations": [{"kind": v.kind, "quote": v.span_text} for v in violations],
        "signals": [{"kind": sg.kind, "quote": sg.span_text} for sg in signals],
        "segments": [
            {"idx": s.idx, "speaker": s.speaker, "start_ms": s.start_ms, "text": s.text}
            for s in call.segments
        ],
    }


async def team_coaching_summary(session: AsyncSession, org, days: int = 30) -> list[dict[str, Any]]:
    """Матрица эффективности менеджеров (MCP polylog_get_team_coaching_summary)."""
    dt_from = datetime.now(UTC) - timedelta(days=days)
    calls = (
        (
            await session.execute(
                select(Call).where(
                    Call.org_id == org.id,
                    Call.state == "done",
                    Call.started_at >= dt_from,
                )
            )
        )
        .scalars()
        .all()
    )
    call_ids = [c.id for c in calls]
    scores = await _scores_map(session, call_ids)
    obj_rows = (
        (
            await session.execute(
                select(Objection).where(Objection.call_id.in_(call_ids))
            )
        )
        .scalars()
        .all()
    )
    viol_rows = (
        (
            await session.execute(
                select(Violation).where(Violation.call_id.in_(call_ids))
            )
        )
        .scalars()
        .all()
    )
    users = (
        (await session.execute(select(User).where(User.org_id == org.id))).scalars().all()
    )
    names = {u.id: u.display_name or u.email for u in users}

    per: dict[uuid.UUID | str, dict[str, Any]] = {}
    for c in calls:
        key = c.agent_user_id if c.agent_user_id else (_agent_ext_of(c) or "unknown")
        bucket = per.setdefault(key, {"calls": 0, "scores": [], "obj_total": 0, "obj_handled": 0, "violations": 0})
        bucket["calls"] += 1
        sc = scores.get(c.id)
        if sc:
            bucket["scores"].append(sc.total)
    for o in obj_rows:
        key = None
        for c in calls:
            if c.id == o.call_id:
                key = c.agent_user_id if c.agent_user_id else (_agent_ext_of(c) or "unknown")
                break
        if key in per:
            per[key]["obj_total"] += 1
            if o.response_status == "handled_success":
                per[key]["obj_handled"] += 1
    viol_by_call: dict[uuid.UUID, int] = {}
    for v in viol_rows:
        viol_by_call[v.call_id] = viol_by_call.get(v.call_id, 0) + 1
    for c in calls:
        key = c.agent_user_id if c.agent_user_id else (_agent_ext_of(c) or "unknown")
        if key in per:
            per[key]["violations"] += viol_by_call.get(c.id, 0)

    items: list[dict[str, Any]] = []
    for key, b in per.items():
        scores_list = b["scores"]
        items.append(
            {
                "agent": names.get(key, str(key)) if isinstance(key, uuid.UUID) else f"вн. номер {key}",
                "calls_total": b["calls"],
                "avg_score": round(sum(scores_list) / len(scores_list), 1) if scores_list else None,
                "objections_total": b["obj_total"],
                "objections_handled_ratio": round(b["obj_handled"] / b["obj_total"], 2) if b["obj_total"] else None,
                "violations": b["violations"],
            }
        )
    items.sort(key=lambda x: x["avg_score"] if x["avg_score"] is not None else -1, reverse=True)
    return items
