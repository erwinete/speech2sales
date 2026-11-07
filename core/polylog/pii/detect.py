"""Детекторы PII (РФ, РБ, Узбекистан) и применение политик mask/redact
(doc 04 §3, ТЗ v3.0 §8.2 — эталон).

Порядок DETECTORS важен (R-04): телефон и email раньше документов; СНИЛС и
паспорта раньше ИНН; паспорт РФ требует разделитель между серией и номером,
поэтому слитные 10 цифр остаются ИНН, а не паспортом.
"""

import re
from dataclasses import dataclass

# Телефоны РФ (+7/8), Беларуси (+375 / 80XX) и Узбекистана (+998 / 998)
_PHONE = re.compile(
    r"(?:"
    r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|(?:\+?375)[\s\-(]*\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|8[\s\-]?0(?:15|16|17|21|22|23|24|25|29|33|44)[\s\-(]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r"|(?:\+?998)[\s\-(]*\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    r")"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Банковская карта: 13–19 цифр группами, проверка Luhn
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# 1. Паспорт РФ: серия (2+2 или 4 цифры) + номер (6 цифр слитно или 3+3 через
#    пробел/дефис — ASR-разбивка, DEF-02) = 10 цифр; разделитель между серией
#    и номером обязателен, поэтому слитные 10 цифр остаются ИНН.
_PASSPORT_RU = re.compile(
    r"\b\d{2}\s?\d{2}[\s\-]+(?:\d{6}|\d{3}[\s\-]\d{3})\b"
)

# 2. Паспорт РБ (Беларусь) и Республики Узбекистан:
#    серии РБ: AB, BM, HB, KH, MP, MC, KB, PP, SP, DP (латиница + кириллица
#    АВ, ВМ, НВ, КН, МР, МС, КВ, РР); РУз: AA, AB, AC, AD, AE, KA, FA
#    (кириллица АА, АВ, АС, АД, АЕ, КА, ФА). Смешанные латинско-кириллические
#    пары — через символьные классы. Номер: слитно \d{7} или ASR-разбивка
#    \d{3}[\s\-]\d{2}[\s\-]\d{2} (DEF-02).
_PASSPORT_BY_UZ = re.compile(
    r"(?i)\b(?:AB|BM|HB|KH|MP|MC|KB|PP|SP|DP|AA|AC|AD|AE|KA|FA|"
    r"АВ|ВМ|НВ|КН|МР|МС|КВ|РР|АА|АС|АД|АЕ|КА|ФА|"
    r"[AА][BВ]|[BВ][MМ]|[HН][BВ]|[KК][HН]|[MМ][PР]|[MМ][CС]|[KК][BВ]|[PР][PР]|"
    r"[AА][AА]|[AА][CС]|[AА][DД]|[AА][EЕ]|[KК][AА]|[FФ][AА])"
    r"[\s\-]?(?:\d{7}|\d{3}[\s\-]\d{2}[\s\-]\d{2})\b"
)

# Контекстный детектор прочих серий после слов «паспорт / серия / ID-карта» —
# проверяется до общего цикла (и до _INN, DEF-02)
_PASSPORT_CONTEXT = re.compile(
    r"(?i)(?:паспорт[ауом]?|серия(?:\s+и\s+номер)?|id[\s\-]карт[аыу])\s*(?:серии\s*)?[:№]?\s*"
    r"([A-ZА-ЯЁ]{2}[\s\-]?(?:\d{7}|\d{3}[\s\-]\d{2}[\s\-]\d{2})|"
    r"\d{2}\s?\d{2}[\s\-]?(?:\d{6}|\d{3}[\s\-]\d{3})|"
    r"\d{2}[\s\-]?\d{7})\b"
)

# 3. Личный (идентификационный) номер гражданина РБ: 14 символов
#    7 цифр + буква + 3 цифры + PB/BA/BI (латиница/кириллица, DEF-02) + цифра
_ID_NUMBER_BY = re.compile(
    r"(?i)\b\d{7}[A-ZА-ЯЁ]\d{3}(?:PB|BA|BI|РВ|ВА|ВІ|[PР][BВ]|[BВ][AА]|[BВ][IІ])\d\b"
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
