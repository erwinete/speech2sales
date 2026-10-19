"""Русские названия возражений из schemas/taxonomy.json (ADR-15 — единый
источник истины таксономии: тренажёр ↔ аналитика ↔ UI-тексты бэка)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# Fallback на случай отсутствия файла (упакованные деплои без schemas/)
FALLBACK: dict[str, str] = {
    "price": "Цена",
    "existing_supplier": "Есть поставщик",
    "send_offer": "Просьба прислать КП",
    "timing": "Сроки",
    "no_authority": "Не тот, кто решает",
    "trust": "Доверие к компании",
    "not_interested": "Не интересно",
    "legal_contract": "Договор / юридические",
    "competitor_compare": "Сравнивают с конкурентом",
    "other": "Другое",
}


@lru_cache(maxsize=1)
def objection_ru() -> dict[str, str]:
    """{schema_enum: русское название} из namespaces.obj таксономии."""
    root = Path(__file__).resolve().parents[3]
    path = root / "schemas" / "taxonomy.json"
    if not path.is_file():
        return dict(FALLBACK)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = {
            item["schema_enum"]: str(item["ru"]).capitalize()
            for item in data.get("namespaces", {}).get("obj", [])
            if item.get("schema_enum") and item.get("ru")
        }
        mapping.setdefault("other", "Другое")
        return mapping or dict(FALLBACK)
    except Exception:  # noqa: BLE001 — битая таксономия не должна ломать API
        return dict(FALLBACK)
