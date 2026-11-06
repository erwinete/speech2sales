"""Детекторы PII (РФ, РБ, Узбекистан) и применение политик mask/redact
(doc 04 §3, ТЗ v3.0 §8.2 — эталон).

Порядок DETECTORS важен (R-04): телефон и email раньше документов; СНИЛС и
паспорта раньше ИНН; паспорт РФ требует разделитель между серией и номером,
поэтому слитные 10 цифр остаются ИНН, а не паспортом.
"""

import re
from dataclasses import dataclass

# Телефоны РФ (+7/8 + 10 цифр), РБ (+375 / 8-0XX + 7 цифр), Узбекистан (+998 + 9 цифр)
_PHONE = re.compile(
    r"(?:"
    r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|\+375[\s\-(]*\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|8[\s\-]?0(?:17|25|29|33|44)[\s\-(]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|\+998[\s\-(]*\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r")"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Банковская карта: 13–19 цифр группами, проверка Luhn
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# 1. Паспорт РФ: 4 цифры серии (2+2) + 6 цифр номера = 10 цифр, разделитель
#    между серией и номером обязателен («45 10 123456», «4510-123456»);
#    слитные 10 цифр уходят в ИНН, а не в паспорт.
_PASSPORT_RU = re.compile(r"\b\d{2}\s?\d{2}[\s\-]\d{6}\b")

# 2. Паспорт РБ (Беларусь) и Республики Узбекистан:
#    серии РБ: AB, BM, HB, KH, MP, MC, KB, PP, SP, DP; Узбекистана: AA, AB, AC,
#    AD, AE, KA, FA; плюс кириллические двойники после ASR (АВ, ВМ, НВ, КН,
#    МР, МС, КВ, РР, АА, АС, АД, АЕ, КА, ФА). Формат: 2 буквы + 7 цифр.
_PASSPORT_BY_UZ = re.compile(
    r"(?i)\b(?:AB|BM|HB|KH|MP|MC|KB|PP|SP|DP|AA|AC|AD|AE|KA|FA|"
    r"АВ|ВМ|НВ|КН|МР|МС|КВ|РР|АА|АС|АД|АЕ|КА|ФА)[\s\-]?\d{7}\b"
)

# Контекстный детектор прочих серий при словах «паспорт / серия / ID-карта»
_PASSPORT_CONTEXT = re.compile(
    r"(?i)(?:паспорт[ауом]?|серия(?:\s+и\s+номер)?|id[\s\-]карт[аыу])\s*[:№]?\s*"
    r"([A-ZА-ЯЁ]{2}[\s\-]?\d{7}|\d{4}[\s\-]?\d{6}|\d{2}[\s\-]?\d{7})\b"
)

# 3. Личный (идентификационный) номер гражданина РБ: 14 символов
#    7 цифр + буква + 3 цифры + PB/BA/BI (и кириллические двойники) + цифра
_ID_NUMBER_BY = re.compile(
    r"(?i)\b\d{7}[A-ZА-ЯЁ]\d{3}(?:PB|BA|BI|РВ|ВА|ВІ)\d\b"
)

# 4. ПИНФЛ Республики Узбекистан: 14 цифр, первая — 3, 4, 5 или 6
_PINFL_UZ = re.compile(r"\b[3456]\d{13}\b")

# СНИЛС РФ (XXX-XXX-XXX XX) и ИНН (10 или 12 цифр)
_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}[\s\-]\d{2}\b")
_INN = re.compile(r"\b(?:\d{10}|\d{12})\b")

DETECTORS: tuple[tuple[str, re.Pattern], ...] = (
    ("phone", _PHONE),
    ("email", _EMAIL),
    ("id_number_by", _ID_NUMBER_BY),
    ("pinfl_uz", _PINFL_UZ),
    ("card", _CARD),
    ("snils", _SNILS),
    ("passport", _PASSPORT_RU),
    ("passport", _PASSPORT_BY_UZ),
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

    # Контекстные паспорта («паспорт АА 1234567», «серия 4510-123456») — раньше
    # общего цикла: контекст точнее, чем голая цифровая маска
    for m in _PASSPORT_CONTEXT.finditer(text):
        s, e = m.span(1)
        val = m.group(1)
        if not overlaps(s, e):
            spans.append(PIISpan(kind="passport", start=s, end=e, value=val, detector="regex:passport_ctx"))
            taken.append((s, e))

    for kind, pattern in DETECTORS:
        for m in pattern.finditer(text):
            value = m.group(0)
            if kind == "card":
                digits = re.sub(r"\D", "", value)
                if not (13 <= len(digits) <= 19) or not _luhn_ok(digits):
                    continue
            if kind == "passport" and pattern is _PASSPORT_RU:
                # Паспорт РФ: ровно 10 цифр (BUG-01, ТЗ v3.0 §8.2)
                if len(re.sub(r"\D", "", value)) != 10:
                    continue
            if overlaps(m.start(), m.end()):
                continue
            spans.append(
                PIISpan(
                    kind=kind,
                    start=m.start(),
                    end=m.end(),
                    value=value,
                    detector=f"regex:{kind}",
                )
            )
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
    keep — без изменений (находки фиксируются); mask/redact — маскирование."""
    spans = detect_pii(text)
    if policy in ("mask", "redact") and spans:
        return mask_text(text), spans
    return text, spans
