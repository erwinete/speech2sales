"""Генератор сценария тренажёра возражений — Слой B обменного формата
(V5-03, ТЗ v5.0 §9.2-3; docs/05-exchange-format.md §2,
schemas/trainer-scenario.schema.json). Из звонка или кластера возражений
собирается учебный сценарий (persona, trigger_phrases из реальных цитат,
ideal_responses, success_criteria), валидный по JSON Schema; ПДн в цитатах
маскируются через PiiSanitizer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from polylog.nlp.taxonomy import objection_ru
from polylog.pii.sanitizer import SanitizerSession, estimate_tokens

SCENARIO_SPEC = "trainer-scenario/1.0"
SCHEMA_VERSION = "1.0.0"

# Рекомендованные ответы по типам возражений (банк ответов v0, doc 02 §5)
_IDEAL_BY_TYPE: dict[str, str] = {
    "price": (
        "Не спорю с ценой: разбираем состав стоимости и сравниваем условия, "
        "ищем вариант под бюджет (рассрочка/объём)."
    ),
    "timing": (
        "Согласен, время дорого — поэтому сразу фиксируем минимальный шаг, "
        "который не займёт больше 15 минут."
    ),
    "competitor": (
        "Здорово, что есть поставщик — сравниваем критерии: что у нас лучше, "
        "а за что вы переплачиваете."
    ),
    "authority": "Понимаю, решение не только ваше — подготовлю материалы, которые удобно показать ЛПР.",
    "budget": "Разберём, какую задачу закрываем и какой эффект даст решение — от этого считаем бюджет.",
    "trust": "Показываю кейсы в вашей отрасли и предлагаю небольшой пилот без обязательств.",
}


def _title_for(objection_types: list[str]) -> str:
    if objection_types:
        ru = objection_ru().get(objection_types[0], objection_types[0])
        return f"Отработка возражения «{ru}» — реальный кейс"
    return "Сценарий тренажёра из реального звонка"


def _success_criteria(scores: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """success_criteria из пунктов активной рубрики (scores от stage_score);
    без рубрики — универсальные критерии по отработке возражений."""
    items: list[dict[str, Any]] = []
    for sc in scores or []:
        for it in sc.get("items") or []:
            item_id = str(it.get("item_id") or "")
            weight = it.get("weight") or 0
            if not item_id:
                continue
            items.append({
                "id": f"crit.{item_id}",
                "description": it.get("title") or item_id,
                "weight": float(weight),
                "detection": {"kind": "semantic", "hint": it.get("explanation") or None},
            })
        if items:
            break  # берём пункты последнего (актуального) скора
    if not items:
        items = [
            {
                "id": "crit.objection_acknowledged",
                "description": "Менеджер признал возражение клиента, не спорит и уточняет детали",
                "weight": 30,
                "detection": {"kind": "semantic", "hint": "фраза согласия + уточняющий вопрос"},
            },
            {
                "id": "crit.objection_answered",
                "description": "Дан содержательный ответ с аргументом или альтернативой",
                "weight": 40,
                "detection": {"kind": "semantic", "hint": "аргумент/кейс/альтернатива"},
            },
            {
                "id": "crit.next_step",
                "description": "Зафиксирован следующий шаг (действие + срок)",
                "weight": 30,
                "detection": {"kind": "semantic", "hint": "конкретное действие и дата"},
            },
        ]
    return items


def build_trainer_scenario(
    call_id: str,
    objections: list[dict[str, Any]],
    scores: list[dict[str, Any]] | None = None,
    pii_policy: str = "mask",
) -> dict[str, Any]:
    """Валидный по schemas/trainer-scenario.schema.json сценарий из возражений
    звонка/кластера. objections — [{type, span_text, response_span?, start_ms?,
    confidence?}]; ПДн в цитатах маскируются (pii_policy: none|mask|redact)."""
    sanitizer = SanitizerSession()
    enabled = pii_policy in ("mask", "redact") and sanitizer.config.enabled

    def clean(text: str | None) -> str:
        if not text:
            return ""
        return sanitizer.sanitize_text(text) if enabled else text

    typed = [o for o in objections if (o.get("span_text") or o.get("quote"))]
    objection_items: list[dict[str, Any]] = []
    for i, o in enumerate(typed, start=1):
        quote = clean(o.get("span_text") or o.get("quote") or "")
        response = clean(o.get("response_span") or o.get("ideal_response") or "")
        ideal = response or _IDEAL_BY_TYPE.get(
            o.get("type") or "",
            "Уточняем детали возражения и разбираем состав проблемы — предлагаем конкретный следующий шаг.",
        )
        objection_items.append({
            "id": f"obj-{i}",
            "trigger_phrases": [quote or o.get("type") or "возражение"],
            "client_quote_ref": {
                "artifact_id": f"call:{call_id}",
                "objection_id": f"obj-{i}",
            },
            "ideal_responses": [{"text": ideal}],
            "bad_responses": [{"text": "Спорим с клиентом о цене без разбора состава стоимости."}],
            "difficulty": 3 if (o.get("confidence") or 0.5) < 0.8 else 2,
        })

    scenario: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": f"scn-{str(call_id)[:12]}",
        "spec": SCENARIO_SPEC,
        "title": _title_for([o.get("type") or "" for o in typed]),
        "description": "Сценарий собран автоматически из реального звонка «Полилога»; цитаты обезличены.",
        "persona": {
            "role": "ЛПР / Клиент B2B",
            "company_profile": "B2B-клиент",
            "temperament": "скептичный",
            "crm_context": "Сценарий из реального звонка",
        },
        "objections": objection_items,
        "success_criteria": _success_criteria(scores),
        "metadata": {
            "source_call_ids": [str(call_id)],
            "language": "ru",
            "license": "CC-BY-4.0",
            "anonymization": pii_policy,
            "created_at": datetime.now(UTC).isoformat(),
        },
    }
    return scenario


def scenario_to_yaml(scenario: dict[str, Any]) -> str:
    """YAML-представление сценария (для выгрузки в тренажёр)."""
    import yaml

    return yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False)


def scenario_size_tokens(scenario: dict[str, Any]) -> int:
    return estimate_tokens(json.dumps(scenario, ensure_ascii=False))
