"""Повторяющиеся нерешённые проблемы (Root-Cause / «Unresolved Repeat», DoD М3).

Детерминированный аналог без ML: тип возражения звучал в ≥2 разных звонках
контакта, и последняя отработка — неуспешная (handled_success). Клиент «ходит
по кругу» — сигнал для РОПа. Используется карточкой Customer 360 и периодической
джобой инсайтов; правовая база — те же данные, что у scorecard (doc 08 §1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

HANDLED_OK = "handled_success"
MIN_DISTINCT_CALLS = 2


def find_repeats(
    call_objections: list[tuple[datetime, list[tuple[str, str | None]]]],
) -> list[dict[str, Any]]:
    """Типы возражений, повторившиеся в ≥2 разных звонках с неуспешной последней
    отработкой. На вход — (started_at, [(type, response_status), ...]) по всем
    звонкам контакта, порядок не важен. Выход — [{type, calls, last_status,
    last_at}] по убыванию числа звонков (then по типу — стабильность)."""
    ordered = sorted(call_objections, key=lambda x: x[0], reverse=True)  # новые сверху
    info: dict[str, dict[str, Any]] = {}
    for started, objections in ordered:
        for ty, status in objections:
            rec = info.setdefault(
                ty, {"call_times": [], "last_status": status, "last_at": started}
            )
            rec["call_times"].append(started)

    out: list[dict[str, Any]] = []
    for ty, rec in info.items():
        distinct = len(set(rec["call_times"]))
        if distinct < MIN_DISTINCT_CALLS or rec["last_status"] == HANDLED_OK:
            continue
        last_at = rec["last_at"]
        out.append({
            "type": ty,
            "calls": distinct,
            "last_status": rec["last_status"],
            "last_at": last_at.isoformat() if hasattr(last_at, "isoformat") else str(last_at),
        })
    out.sort(key=lambda x: (-x["calls"], x["type"]))
    return out
