"""Детекторы PII (regex v0) и применение политик mask/redact (doc 04 §3)."""

import re
from dataclasses import dataclass

# RU-телефоны: +7/8 + 10 цифр, различные разделители; 6+ подряд цифр без смысла — не матчим
_PHONE = re.compile(
    r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# банковская карта: 13–19 цифр группами, проверка Luhn
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PASSPORT = re.compile(r"\b\d{2}\s?\d{2}\s?\d{6}\b")
_INN = re.compile(r"\b(?:\d{10}|\d{12})\b")

DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("phone", _PHONE),
    ("email", _EMAIL),
    ("card", _CARD),
    ("passport", _PASSPORT),
    ("inn", _INN),
)


@dataclass
class PIISpan:
    kind: str
    start: int
    end: int
    value: str
    detector: str


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def detect_pii(text: str) -> list[PIISpan]:
    spans: list[PIISpan] = []
    taken: list[tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(s < te and ts < e for ts, te in taken)

    for kind, pattern in DETECTORS:
        for m in pattern.finditer(text):
            value = m.group(0)
            if kind == "card":
                digits = re.sub(r"\D", "", value)
                if not (13 <= len(digits) <= 19) or not _luhn_ok(digits):
                    continue
            if kind == "passport":
                # исключаем совпадения с длинными номерами (карты/ИНН обрабатываются раньше)
                if len(re.sub(r"\D", "", value)) != 8:
                    continue
            if overlaps(m.start(), m.end()):
                continue
            spans.append(PIISpan(kind=kind, start=m.start(), end=m.end(), value=value, detector=f"regex:{kind}"))
            taken.append((m.start(), m.end()))
    spans.sort(key=lambda s: s.start)
    return spans


def mask_text(text: str, placeholder: str = "[ПДн]") -> str:
    """mask-политика: замена найденных PII на плейсхолдер (doc 04 §3)."""
    spans = detect_pii(text)
    if not spans:
        return text
    out = text
    for s in reversed(spans):
        out = out[: s.start] + placeholder + out[s.end :]
    return out


def apply_policy(text: str, policy: str) -> tuple[str, list[PIISpan]]:
    """Возвращает (текст после политики, находки). Политики doc 04 §3:
    keep — текст без изменений (находки фиксируются); mask — маскирование;
    redact — маскирование (физическое удаление из экспорта делает export-слой)."""
    spans = detect_pii(text)
    if policy in ("mask", "redact") and spans:
        return mask_text(text), spans
    return text, spans
