"""Next Best Action (DoD М3): детерминированный rule-engine вместо промптов —
матрица [риск-scorecard] + [повторы/возражения] + [сигналы последнего звонка]
→ до трёх рекомендаций для менеджера по убыванию приоритета. Чистая функция —
покрыта тестами без БД/моделей; подключается к карточке Customer 360."""

from __future__ import annotations

from typing import Any

from polylog.nlp.sentiment import sentiment_emoji
from polylog.nlp.taxonomy import objection_ru


def next_best_actions(
    risk: dict[str, Any] | None,
    repeats: list[dict[str, Any]],
    stats: dict[str, Any],
    last_call: dict[str, Any] | None,
    sentiment: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """[{action, reason, priority}] — приоритет 0 самый срочный.

    last_call: {"score_total", "objections": [{"type", "response_status"}],
    "signals": [kind, ...], "started_at"}; sentiment: клиентский агрегат
    последнего звонка {score, positive, negative}."""
    actions: list[dict[str, str]] = []

    band = (risk or {}).get("band")
    days_silence = (risk or {}).get("factors", [])
    silence_days = next(
        (f.get("value") for f in days_silence if f.get("feature") == "days_silence"),
        None,
    )

    if repeats:
        worst = repeats[0]
        type_ru = objection_ru().get(worst["type"], worst["type"])
        actions.append({
            "action": "Сменить подход по возражению",
            "reason": (
                f"«{type_ru}» прозвучало в {worst['calls']} звонках без успеха — "
                "подготовьте новый аргумент или подключите старшего"
            ),
            "priority": "0",
        })

    if band == "high" or (isinstance(silence_days, (int, float)) and silence_days >= 7):
        d = f" (тишина {int(silence_days)} дн.)" if isinstance(silence_days, (int, float)) else ""
        actions.append({
            "action": "Перезвонить клиенту",
            "reason": f"риск потери {((risk or {}).get('score', '—'))}/100{d} — клиент уходит",
            "priority": "1",
        })

    if last_call:
        unhandled_price = any(
            o.get("type") == "price" and o.get("response_status") != "handled_success"
            for o in last_call.get("objections", [])
        )
        if unhandled_price:
            actions.append({
                "action": "Отправить КП с ценами",
                "reason": "в последнем разговоре не закрыто возражение про цену",
                "priority": "2",
            })
        if "next_step_agreed" in (last_call.get("signals") or []):
            actions.append({
                "action": "Подтвердить договорённость",
                "reason": "в последнем звонке согласован следующий шаг — не дать ему расплыться",
                "priority": "3",
            })
        score_total = last_call.get("score_total")
        if score_total is not None and score_total < 40:
            actions.append({
                "action": "Разобрать звонок с РОПом",
                "reason": f"низкая оценка последнего звонка ({score_total}/100) — коучинг по скрипту",
                "priority": "4",
            })

    if sentiment and sentiment.get("negative", 0) >= 2 and (sentiment.get("score") or 0) < -0.2:
        actions.append({
            "action": "Снизить накал",
            "reason": (
                f"клиент негативно настроен {sentiment_emoji(sentiment.get('score'))} — "
                "начните с решения его проблемы, а не с презентации"
            ),
            "priority": "5",
        })

    if not actions and stats.get("calls_total"):
        actions.append({
            "action": "Поддерживать контакт",
            "reason": "критичных сигналов нет — отправьте полезные материалы, чтобы не остыть",
            "priority": "7",
        })
    if not stats.get("calls_total"):
        return []

    actions.sort(key=lambda a: a["priority"])
    return actions[:3]
