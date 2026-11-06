"""Детерминированный санитайзер ПДн со слайдер-настройками (ТЗ v3.0 §4.2,
BUG-02): подготовка транскриптов и карточек звонков перед отправкой во внешнюю
LLM или MCP-тулзу. 152-ФЗ Safe Mode.

Ключевые свойства:
- консистентная замена в рамках одной сессии: первый встреченный телефон
  становится [ТЕЛЕФОН_1] и везде заменяется на него же; второй — [ТЕЛЕФОН_2];
- внутренние UUID/external_id → короткие алиасы [CALL_#1], [CONTACT_#1];
  обратный маппинг alias_map возвращается на фронт, чтобы ссылки в отчёте
  LLM превращались в кликабельные ссылки на звонки;
- статистика SanitizationStats: сколько и чего вырезано.

Известное ограничение: словесная запись телефона («восемь девятьсот …»)
поддерживается для полных последовательностей 9-11 цифровых слов; частичные
конструкции не матчатся сознательно — цена ложного срабатывания выше цены
пропуска.
"""

from __future__ import annotations

import re
import uuid as uuid_mod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

# ── Регулярные выражения ──

_PHONE = re.compile(r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
_PHONE_ALT = re.compile(r"\b\d{3}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}\b")  # без +7/8
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PASSPORT = re.compile(r"\b\d{2}\s?\d{2}\s?\d{6}\b")
_INN = re.compile(r"\b(?:\d{10}|\d{12})\b")
_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}[\s\-]\d{2}\b")
# заказ № 45120 / договор 124/26 / счёт №8812 / заявка AB-193 (ТЗ §4.2.3)
_ORDER = re.compile(
    r"(?i)\b(?:заказ[ауеом]?|договор[ауеом]?|сч[её]т[ауеом]?|счет[ауеом]?|"
    r"накладн(?:ая|ой|ую)|заявк[аиеу]|тикет|ордер|order)\s*(?:№|номер|#|:)?\s*"
    r"([A-Za-zА-Яа-я0-9\-/]{3,24})\b"
)
# ФИО: «Иванов Иван Иванович» → «Иван Иванович» → одиночный отчествоподобный
_PATRONYMIC = re.compile(r"\b[А-ЯЁ][а-яё]{2,20}(?:ович|евич|ич|овна|евна|ична|чна)\b")
_FIO_FULL = re.compile(r"\b[А-ЯЁ][а-яё]{2,20}\s+[А-ЯЁ][а-яё]{2,20}\s+[А-ЯЁ][а-яё]{2,20}\b")
_FIO_PAIR = re.compile(r"\b[А-ЯЁ][а-яё]{2,20}\s+[А-ЯЁ][а-яё]{2,20}\b")
# представление в диалоге: «меня зовут Ирина», «это звонит Сергей Петрович» —
# заменяется только само имя (группа 1), маркер остаётся в тексте
_INTRO_NAME = re.compile(
    r"(?:меня зовут|это звонит|моё имя|мое имя|обращаться к вам|товарищ|господин|госпожа)\s+"
    r"([А-ЯЁ][а-яё]{1,15}(?:\s+[А-ЯЁ][а-яё]{2,20})?)",
    re.IGNORECASE,
)
# компании: ООО/ИП/АО + название
_COMPANY = re.compile(
    r"\b(?:ООО|ИП|АО|ЗАО|ОАО|ПАО)\s*(?:«[^»]{1,40}»|[А-ЯЁ][А-ЯЁа-яёA-Za-z\- ]{1,40})"
)
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# словесная запись: 9-11 цифровых слов подряд («восемь девятьсот один …»)
_NUM_WORDS = (
    "ноль|один|два|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|"
    "двенадцать|тринадцать|четырнадцать|пятнадцать|шестнадцать|семнадцать|"
    "восемнадцать|девятнадцать|двадцать"
)
_PHONE_SPOKEN = re.compile(
    rf"\b(?:{_NUM_WORDS})(?:[\s\-]+(?:{_NUM_WORDS})){{8,10}}\b", re.IGNORECASE
)

CATEGORY_ALIAS: dict[str, str] = {
    "names": "ФИО",
    "phones_emails": "ТЕЛЕФОН",
    "orders_contracts": "ЗАКАЗ_ДОГОВОР",
    "companies": "КОМПАНИЯ",
    "internal_ids": "ID",
    "custom": "СТОП",
}

# алиасы с решёткой по ТЗ: [CALL_#1], [CONTACT_#1], [DEAL_#1], [ID_#1]
HASH_LABELS = {"ID", "CALL", "CONTACT", "DEAL", "THREAD"}

# kind → категория статистики
_KIND_CATEGORY: dict[str, str] = {
    "phone": "phones_emails", "phone_alt": "phones_emails",
    "phone_spoken": "phones_emails", "email": "phones_emails",
    "card": "orders_contracts", "passport": "orders_contracts",
    "inn": "orders_contracts", "snils": "orders_contracts", "order": "orders_contracts",
    "fio_full": "names", "fio_pair": "names", "intro_name": "names",
    "patronymic": "names",
    "company": "companies",
    "uuid": "internal_ids",
}


class PiiSanitizerConfig(BaseModel):
    """Состояние слайдера очистки ПДн (ТЗ v3.0 §4.2.2)."""

    enabled: bool = True                  # главный слайдер — ВКЛ по умолчанию
    strip_names: bool = True              # ФИО и имена людей
    strip_phones_emails: bool = True      # телефоны и email
    strip_orders_contracts: bool = True   # заказы, договоры, счета, карты, паспорта, ИНН
    strip_internal_ids: bool = True       # UUID/external_id → [CALL_#1]
    strip_company_names: bool = False     # названия компаний и юр-формы
    custom_stop_words: list[str] = Field(default_factory=list)


@dataclass
class SanitizationStats:
    total_redactions: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    alias_map: dict[str, str] = field(default_factory=dict)  # alias → реальное значение

    def bump(self, category: str) -> None:
        self.total_redactions += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1


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


def _phone_key(value: str) -> str:
    """Канонический ключ телефона: последние 10 цифр (+7/8 не различаются)."""
    digits = re.sub(r"\D", "", value)
    return digits[-10:] if digits else value


class PiiSanitizer:
    """Сессия очистки: один экземпляр на один пакет (запрос preview/analyze,
    один вызов MCP-тулзы). Словарь (категория, ключ) → alias гарантирует, что
    один и тот же человек/телефон/заказ получает один и тот же алиас."""

    def __init__(self, config: PiiSanitizerConfig | None = None):
        self.config = config or PiiSanitizerConfig()
        self.stats = SanitizationStats()
        self._aliases: dict[tuple[str, str], str] = {}  # (category, key) → alias
        self._counters: dict[str, int] = {}
        self._real_index: dict[str, str] = {}  # real.lower() → alias (для UUID в тексте)

    # ── алиасы ──

    def _alias(self, category: str, key: str, real: str, label: str) -> str:
        """Alias для ключа (стабильный в рамках сессии) + регистрация в alias_map."""
        cache_key = (category, key)
        if cache_key not in self._aliases:
            n = self._counters.get(label, 0) + 1
            self._counters[label] = n
            self._aliases[cache_key] = (
                f"[{label}_#{n}]" if label in HASH_LABELS else f"[{label}_{n}]"
            )
            self.stats.alias_map[self._aliases[cache_key]] = real
        return self._aliases[cache_key]

    def register_id(self, kind: str, real_id: str | uuid_mod.UUID | None) -> str:
        """Структурный ID (call/contact/deal/company) → алиас [CALL_#N] и т.п.
        Вызывается для полей карточки звонка; текстовая замена не выполняется."""
        if real_id is None or real_id == "":
            return ""
        label = {
            "call": "CALL", "contact": "CONTACT", "deal": "DEAL",
            "company": "COMPANY", "user": "AGENT", "thread": "THREAD",
        }.get(kind, "ID")
        real = str(real_id)
        cache_key = ("internal_ids", f"{kind}:{real.lower()}")
        if cache_key in self._aliases:
            return self._aliases[cache_key]  # повторная регистрация — без двойного счёта
        alias = self._alias(*cache_key, real, label)
        self._real_index[real.lower()] = alias
        self.stats.bump("internal_ids")
        return alias

    # ── детекция в тексте ──

    def _find_spans(self, text: str) -> list[tuple[int, int, str, str]]:
        """(start, end, kind, value) без перекрытий, длинные совпадения — раньше."""
        raw: list[tuple[int, int, str, str]] = []

        def add(pattern: re.Pattern, kind: str, check=None, group: int = 0):
            for m in pattern.finditer(text):
                value = m.group(group)
                if not value:
                    continue
                if check and not check(value, m):
                    continue
                raw.append((m.start(group), m.end(group), kind, value))

        if self.config.strip_phones_emails:
            add(_PHONE, "phone")
            add(_PHONE_ALT, "phone_alt")
            add(_PHONE_SPOKEN, "phone_spoken")
            add(_EMAIL, "email")
        if self.config.strip_orders_contracts:
            def _card_ok(value, _m):
                digits = re.sub(r"\D", "", value)
                return 13 <= len(digits) <= 19 and _luhn_ok(digits)

            def _passport_ok(value, _m):
                return len(re.sub(r"\D", "", value)) == 10

            add(_CARD, "card", _card_ok)
            add(_INN, "inn")  # границы \b уже ограничивают 10/12 цифр
            add(_PASSPORT, "passport", _passport_ok)
            add(_SNILS, "snils")
            add(_ORDER, "order")
        if self.config.strip_names:
            add(_FIO_FULL, "fio_full")
            add(_FIO_PAIR, "fio_pair")
            add(_INTRO_NAME, "intro_name", group=1)
            add(_PATRONYMIC, "patronymic")
        if self.config.strip_company_names:
            add(_COMPANY, "company")
        if self.config.strip_internal_ids:
            add(_UUID, "uuid")

        raw.sort(key=lambda s: (s[0], -(s[1] - s[0])))  # по позиции, длинные раньше
        taken: list[tuple[int, int]] = []
        out: list[tuple[int, int, str, str]] = []
        for s, e, kind, value in raw:
            if any(s < te and ts < e for ts, te in taken):
                continue
            out.append((s, e, kind, value))
            taken.append((s, e))
        out.sort(key=lambda s: s[0])
        return out

    def _label_of(self, kind: str) -> str:
        if kind == "email":
            return "EMAIL"
        return CATEGORY_ALIAS[_KIND_CATEGORY[kind]]

    # ── замена ──

    def sanitize_text(self, text: str) -> str:
        """Очистка произвольного текста (реплика, цитата, промпт-контекст)."""
        if not self.config.enabled or not text:
            return text
        for word in self.config.custom_stop_words:
            word = word.strip()
            if not word:
                continue
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            alias = self._alias("custom", word.casefold(), word, "СТОП")
            text, n = pattern.subn(alias, text)
            for _ in range(n):
                self.stats.bump("custom")
        spans = self._find_spans(text)
        if not spans:
            return text
        out = text
        for s, e, kind, value in reversed(spans):
            if kind == "uuid":
                alias = self._real_index.get(value.lower())
                if alias is None:
                    alias = self._alias("internal_ids", value.lower(), value, "ID")
            else:
                key = _phone_key(value) if kind in ("phone", "phone_alt", "phone_spoken") else value.casefold()
                alias = self._alias(_KIND_CATEGORY[kind], key, value, self._label_of(kind))
            out = out[:s] + alias + out[e:]
            self.stats.bump(_KIND_CATEGORY[kind])
        return self.replace_known(out)

    def replace_known(self, text: str) -> str:
        """Замена уже зарегистрированных значений сессии (имена, компании) по
        словарю: display_name контакта и ФИО агента попадают в текст реплик."""
        if not self.config.enabled:
            return text
        for (category, _key), alias in list(self._aliases.items()):
            real = self.stats.alias_map.get(alias)
            if not real or category not in ("names", "companies"):
                continue
            pattern = re.compile(re.escape(real), re.IGNORECASE)
            text, n = pattern.subn(alias, text)
            for _ in range(n):
                self.stats.bump(category)
        return text

    def sanitize_phone(self, value: str) -> str:
        """Структурный номер (phone_from/phone_to): тот же ключ, что у телефонов
        в тексте → один и тот же алиас во всём пакете."""
        if not self.config.enabled or not value:
            return value
        alias = self._alias("phones_emails", _phone_key(value), value, "ТЕЛЕФОН")
        self.stats.bump("phones_emails")
        return alias

    def sanitize_value(self, value: str, category: str, label: str | None = None) -> str:
        """Очистка структурного поля (phone_from, display_name, external_id):
        регистрирует алиас и возвращает его без текстового разбора."""
        if not self.config.enabled or not value:
            return value
        alias = self._alias(category, value.casefold(), value, label or CATEGORY_ALIAS.get(category, "ID"))
        self.stats.bump(category)
        return alias

    def sanitize_obj(self, obj: Any) -> Any:
        """Рекурсивная очистка dict/list/str (пакет данных для LLM)."""
        if isinstance(obj, str):
            return self.sanitize_text(obj)
        if isinstance(obj, dict):
            return {k: self.sanitize_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.sanitize_obj(v) for v in obj]
        return obj


def estimate_tokens(text: str) -> int:
    """Грубая оценка объёма контекста в токенах (ТЗ v3.0 §4.3, режим 3)."""
    return max(1, len(text) // 3) if text else 0
