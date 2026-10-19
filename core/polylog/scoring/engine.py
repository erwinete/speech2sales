"""Rubric-engine: версия рубрики + вычисление пунктов с evidence (doc 02 §4).

Rule kinds:
  lexicon     — скриптовый маркер в scope (first_60s|last_60s), patterns по имени группы
  predicate   — метрика (из call_metrics) с оператором op и value
  signal      — наличие сигнала sig.* (с порогом по минимальному confidence)
  signal_any  — любой из списка сигналов
  objections  — агрегат по возражениям: handled_success_ratio / count / unhandled_count
  violations  — количество нарушений op value
"""

import re
from typing import Any

from polylog.nlp import lexicons as L
from polylog.nlp.rules import Finding, handled_success_ratio, lexicon_hit

SCORER_VERSION = "rubric-engine@0.1.0"

DEFAULT_RUBRIC_NAME = "default_b2b_v1"

DEFAULT_RUBRIC_SPEC: dict[str, Any] = {
    "rubric_id": DEFAULT_RUBRIC_NAME,
    "version": 2,
    "max_score": 100,
    "items": [
        {"id": "greeting", "title": "Приветствие: компания + имя", "weight": 10,
         "rule": {"kind": "lexicon", "lexicon": "greeting", "scope": "first_60s"}},
        {"id": "needs", "title": "Выявление потребностей ≥ 2 открытых вопросов", "weight": 15,
         "rule": {"kind": "predicate", "metric": "agent_questions", "op": ">=", "value": 2}},
        {"id": "objections", "title": "Возражения отработаны (≥ 50% успешно)", "weight": 20,
         "rule": {"kind": "objections", "condition": "handled_success_ratio", "op": ">=", "value": 0.5}},
        {"id": "next_step", "title": "Зафиксирован следующий шаг", "weight": 15,
         "rule": {"kind": "signal", "signal": "next_step_agreed"}},
        {"id": "details", "title": "Интерес к деталям/демо", "weight": 10,
         "rule": {"kind": "signal_any", "signals": ["details_requested", "demo_positive"]}},
        {"id": "forbidden", "title": "Нет запрещённых фраз", "weight": 10,
         "rule": {"kind": "violations", "op": "==", "value": 0}},
        {"id": "questions_answered", "title": "Вопросы клиента отвечены (NLI ≥ 50%)", "weight": 10,
         "rule": {"kind": "predicate", "metric": "nli_answered_ratio", "op": ">=", "value": 0.5,
                  "skip_if_missing": True}},
        {"id": "closing", "title": "Корректное завершение разговора", "weight": 10,
         "rule": {"kind": "lexicon", "lexicon": "closing", "scope": "last_60s"}},
    ],
}

_LEXICON_GROUPS: dict[str, tuple[re.Pattern, ...]] = {
    "greeting": L.GREETING_PATTERNS,
    "closing": L.CLOSING_PATTERNS,
}

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def evaluate(
    rubric_spec: dict[str, Any],
    *,
    segments: list[dict],
    metrics: dict[str, Any],
    findings: list[Finding],
) -> dict[str, Any]:
    """Возвращает {total, max_score, items:[...]} — каждый пункт с evidence (doc 02 §4.2)."""
    objections = [f for f in findings if f.kind == "objection"]
    signals = [f for f in findings if f.kind == "signal"]
    violations = [f for f in findings if f.kind == "violation"]

    items_out: list[dict[str, Any]] = []
    total = 0.0
    max_score = float(rubric_spec.get("max_score", 100))

    for item in rubric_spec["items"]:
        rule = item["rule"]
        kind = rule["kind"]
        score = 0.0
        explanation = ""
        evidence: list[dict[str, Any]] = []

        if kind == "lexicon":
            hit = lexicon_hit(segments, _LEXICON_GROUPS[rule["lexicon"]], rule["scope"])
            score = float(item["weight"]) if hit else 0.0
            where = "в начале звонка" if rule["scope"] == "first_60s" else "в конце звонка"
            missing_what = (
                "Приветствие и представление"
                if rule["lexicon"] == "greeting"
                else "Прощание и итоги"
            )
            explanation = (
                f"Прозвучало {where}: «{hit['span_text'][:80]}»"
                if hit
                else f"{missing_what} {where} не прозвучали"
            )
            if hit:
                evidence.append(
                    {"ref_type": "segment", "ref_id": str(hit["segment_idx"]),
                     "span": hit["span_text"], "start_ms": hit["start_ms"], "method": "lexicon"}
                )

        elif kind == "predicate":
            value, found = _resolve_metric(metrics, rule["metric"])
            if not found and rule.get("skip_if_missing"):
                score = float(item["weight"])
                explanation = "В этом звонке таких ситуаций не было — пункт засчитан"
                evidence.append({"ref_type": "metric", "ref_id": rule["metric"],
                                 "span": "n/a", "start_ms": None, "method": "metric-skip"})
            elif rule["metric"] == "agent_questions":
                ok = _OPS[rule["op"]](value, rule["value"])
                score = float(item["weight"]) if ok else 0.0
                explanation = (
                    "Менеджер не задал ни одного открытого вопроса"
                    if value == 0
                    else f"Менеджер задал открытых вопросов: {int(value)}"
                )
                evidence.append({"ref_type": "metric", "ref_id": rule["metric"],
                                 "span": str(int(value)), "start_ms": None, "method": "metric"})
            elif rule["metric"] == "nli_answered_ratio":
                nli = metrics.get("nli") or {}
                pairs, answered = int(nli.get("pairs", 0)), int(nli.get("answered", 0))
                pct = int(answered / pairs * 100) if pairs else 0
                ok = _OPS[rule["op"]](value, rule["value"]) and pairs > 0
                score = float(item["weight"]) if ok else 0.0
                explanation = (
                    f"Клиент задал {pairs} вопрос(ов), по существу отвечено: {answered} ({pct}%)"
                )
                evidence.append({"ref_type": "metric", "ref_id": rule["metric"],
                                 "span": f"{answered} из {pairs}", "start_ms": None,
                                 "method": "nli"})

        elif kind == "signal":
            hits = [s for s in signals if s.type == rule["signal"]]
            score = float(item["weight"]) if hits else 0.0
            explanation = (
                f"Прозвучало: «{hits[0].span_text[:80]}»"
                if hits
                else "В разговоре не зафиксировано"
            )
            evidence.extend(_finding_evidence(hits[:1]))

        elif kind == "signal_any":
            hits = [s for s in signals if s.type in rule["signals"]]
            score = float(item["weight"]) if hits else 0.0
            explanation = (
                f"Прозвучало: «{hits[0].span_text[:80]}»"
                if hits
                else "В разговоре не зафиксировано"
            )
            evidence.extend(_finding_evidence(hits[:1]))

        elif kind == "objections":
            value = (
                handled_success_ratio(objections)
                if rule["condition"] == "handled_success_ratio"
                else len(objections)
            )
            ok = _OPS[rule["op"]](value, rule["value"])
            # без возражений критерий считается выполненным (нет риска)
            if rule["condition"] == "handled_success_ratio" and not objections:
                ok, value = True, 1.0
                explanation = "Возражений в разговоре не прозвучало"
            else:
                handled = sum(1 for o in objections if o.response_status == "handled_success")
                explanation = (
                    f"Возражений: {len(objections)}, из них успешно отработано: {handled}"
                )
            score = float(item["weight"]) if ok else 0.0
            evidence.extend(_finding_evidence(objections[:2]))

        elif kind == "violations":
            value = len(violations)
            ok = _OPS[rule["op"]](value, rule["value"])
            score = float(item["weight"]) if ok else 0.0
            explanation = (
                "Запрещённых фраз и нарушений не выявлено"
                if value == 0
                else f"Выявлено нарушений: {value} — см. цитаты ниже"
            )
            evidence.extend(_finding_evidence(violations[:2]))

        else:  # неизвестный rule.kind — безопасно обнуляем с объяснением
            explanation = f"Неизвестный тип правила: {kind}"

        total += score
        items_out.append({
            "item_id": item["id"],
            "title": item.get("title"),
            "score": score,
            "weight": float(item["weight"]),
            "explanation": explanation,
            "evidence": evidence,
        })

    return {"total": round(total, 2), "max_score": max_score, "items": items_out}


def _finding_evidence(findings: list[Finding]) -> list[dict[str, Any]]:
    return [
        {
            "ref_type": f.kind,
            "ref_id": f"{f.kind}:{f.type}:{f.segment_idx}",
            "span": f.span_text,
            "start_ms": f.start_ms,
            "method": f.model_id,
        }
        for f in findings
    ]


def _resolve_metric(metrics: dict[str, Any], path: str) -> tuple[Any, bool]:
    """Поддержка путей agent_questions / questions.total / talk_ratio.agent.
    Возвращает (значение, найдено)."""
    cur: Any = metrics
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return 0, False
    return (cur, True) if isinstance(cur, (int, float)) else (0, False)
