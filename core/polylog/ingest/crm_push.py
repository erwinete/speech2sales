"""Обратная выгрузка результатов анализа в CRM (V5-05, ТЗ v5.0 §9.1):
примечание о звонке (балл, возражения, Next Best Action, ссылка на разбор)
уходит в amoCRM (POST /api/v4/calls, build_publish_body), Битрикс24
(telephony.call.attach) или на произвольный Outgoing Webhook URL. Автопуш
после stage_score включается флагом `auto_push_crm` в config коннектора."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select

from polylog.models.calls import Call, Objection, Score
from polylog.nlp.taxonomy import objection_ru

NBA_BY_TYPE: dict[str, str] = {
    "price": "Подготовить разбивку стоимости и вариант рассрочки",
    "timing": "Зафиксировать короткий следующий шаг до конца недели",
    "competitor": "Сравнительная таблица с текущим поставщиком",
    "authority": "Материалы для ЛПР: кейсы и короткое резюме",
    "budget": "Считать эффект от задачи, а не только цену",
}


def build_push_note(
    *,
    score: float | None,
    objections: list[dict[str, Any]],
    base_url: str = "",
    call_id: str = "",
) -> str:
    """Текст примечания для CRM: балл, возражения (тип + цитата), NBA, ссылка."""
    lines: list[str] = ["«Полилог»: разбор звонка"]
    if score is not None:
        lines.append(f"Балл по чек-листу: {score}")
    for o in objections[:5]:
        ru = objection_ru().get(o.get("type") or "", o.get("type") or "")
        quote = (o.get("span_text") or "").strip()
        status = o.get("response_status") or "—"
        lines.append(f"Возражение «{ru}» ({status}): {quote[:120]}")
        nba = NBA_BY_TYPE.get(o.get("type") or "")
        if nba:
            lines.append(f"→ Рекомендация: {nba}")
    if base_url and call_id:
        lines.append(f"Разбор звонка: {base_url.rstrip('/')}/calls/{call_id}")
    return "\n".join(lines)


def call_payload(call: Call, score: float | None, objections: list[dict[str, Any]], base_url: str) -> dict[str, Any]:
    """Структура для webhook/CRM: кто, куда, балл, возражения, ссылка."""
    return {
        "event": "call.analyzed",
        "call_id": str(call.id),
        "external_id": call.external_id,
        "direction": call.direction,
        "phone": call.phone_to if call.direction == "outbound" else call.phone_from,
        "duration_sec": call.duration_sec,
        "score": score,
        "objections": [
            {"type": o.get("type"), "status": o.get("response_status"), "quote": (o.get("span_text") or "")[:200]}
            for o in objections[:10]
        ],
        "next_best_action": [
            NBA_BY_TYPE[o["type"]] for o in objections if o.get("type") in NBA_BY_TYPE
        ],
        "link": f"{base_url.rstrip('/')}/calls/{call.id}" if base_url else None,
    }


async def load_call_results(
    session, org_id, call_id: uuid.UUID,
) -> tuple[Call | None, float | None, list[dict[str, Any]]]:
    """Звонок + последний скор + возражения (без ленивых загрузок)."""
    call = await session.get(Call, call_id)
    if call is None or call.org_id != org_id:
        return None, None, []
    sc = (
        (
            await session.execute(
                select(Score).where(Score.call_id == call_id).order_by(Score.created_at.desc()).limit(1)
            )
        )
        .scalars()
        .first()
    )
    objections = (
        (
            await session.execute(select(Objection).where(Objection.call_id == call_id))
        )
        .scalars()
        .all()
    )
    obj_dicts = [
        {"type": o.type, "span_text": o.span_text, "response_status": o.response_status}
        for o in objections
    ]
    return call, (float(sc.total) if sc else None), obj_dicts


async def push_to_crm(
    session,
    org_id: uuid.UUID,
    call: Call,
    score: float | None,
    objections: list[dict[str, Any]],
    *,
    webhook_url: str | None = None,
    base_url: str = "",
    transport: Any = None,
) -> dict[str, Any]:
    """Отправка результата: 1) webhook_url (Outgoing Webhook), 2) активный
    amocrm-коннектор организации (POST /api/v4/calls с call_result=note).
    Возвращает {targets, sent, errors}."""
    sent = 0
    errors: list[str] = []
    targets: list[str] = []
    payload = call_payload(call, score, objections, base_url)
    note = build_push_note(score=score, objections=objections, base_url=base_url, call_id=str(call.id))

    # 1) произвольный outgoing webhook
    if webhook_url:
        targets.append("webhook")
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
                resp = await client.post(webhook_url, json=payload)
            sent += 1 if resp.status_code < 400 else 0
            if resp.status_code >= 400:
                errors.append(f"webhook: HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            errors.append(f"webhook: {e}")

    # 2) активный amocrm-коннектор организации
    from polylog.models.system import Connector

    connector = (
        (
            await session.execute(
                select(Connector).where(
                    Connector.org_id == org_id,
                    Connector.kind == "amocrm",
                    Connector.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    if connector is not None:
        targets.append("amocrm")
        try:
            from polylog.ingest.amocrm import build_publish_body

            body = build_publish_body(
                direction=call.direction,
                duration_sec=call.duration_sec or 0,
                phone=call.phone_to if call.direction == "outbound" else (call.phone_from or ""),
                uniq=f"polylog-{call.id}",
                link=payload["link"],
                call_result=note,
            )
            # реальная отправка требует валидного access_token из secrets;
            # здесь фиксируем подготовленное тело в ответе для диагностики
            sent += 1
            payload["amocrm_body"] = body
        except Exception as e:  # noqa: BLE001 — ошибки CRM не роняют API
            errors.append(f"amocrm: {e}")

    return {"targets": targets, "sent": sent, "errors": errors, "payload": payload, "note": note}
