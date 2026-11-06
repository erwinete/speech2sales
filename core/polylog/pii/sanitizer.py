"""Детерминированный санитайзер ПДн для LLM и MCP (ТЗ v3.0 §4.2, §8.3 —
эталон; 152-ФЗ Safe Mode). Консистентная замена внутри сессии/бандла:
  - ФИО и имена → [ФИО_1], [ФИО_2]
  - Телефоны РФ/РБ/УЗ и Email → [ТЕЛЕФОН_1], [EMAIL_1]
  - Номера заказов, договоров, счетов, карт, паспортов (РФ/РБ/УЗ), ПИНФЛ,
    личных номеров РБ, ИНН, СНИЛС → [ЗАКАЗ_ДОГОВОР_1], [ПАСПОРТ_1], [КАРТА_1],
    [ИНН_1], [СНИЛС_1], [ЛИЧНЫЙ_НОМЕР_РБ_1], [ПИНФЛ_УЗ_1]
  - Внутренние и CRM ID → [CALL_#1], [CONTACT_#1], [DEAL_#1], [EXT_1]
  - Названия компаний → [КОМПАНИЯ_1]; стоп-слова → [СКРЫТО_1]

Порядок прохода (R-04): detect_pii (телефон/email/документы по порядку
детекторов) → номера заказов → компании → ФИО → имена-представления.
Двухфазная замена (сбор спанов → обратная подстановка с конца) защищает уже
вставленные плейсхолдеры (R-05).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from polylog.pii.detect import PIISpan, detect_pii

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_ORDER_CONTRACT_RE = re.compile(
    r"(?i)\b(заказ[ауеом]?|договор[ауеом]?|контракт[ауеом]?|сч[её]т[ауеом]?|"
    r"накладн(?:ая|ой|ую)|заявк[аиеу]|тикет[ау]?|ордер[ау]?|order|invoice)\s*"
    r"(?:№|номер|#|:)?\s*([A-Za-zА-Яа-я0-9][\w\-/]{2,22})\b"
)

_FIO_PATRONYMIC_RE = re.compile(
    r"\b([А-ЯЁ][а-яё]{1,22}\s+[А-ЯЁ][а-яё]{2,20}(?:ович|евич|ич|овна|евна|ична|чна)"
    r"(?:\s+[А-ЯЁ][а-яё]{1,22})?|"
    r"[А-ЯЁ][а-яё]{2,22}(?:ов|ев|ин|ын|ский|цкий|ой|ая|яя|ко|ук|юк|чук)\s+"
    r"[А-ЯЁ][а-яё]{2,20}\s+[А-ЯЁ][а-яё]{2,20}(?:ович|евич|ич|овна|евна|ична|чна))\b"
)

_INTRO_NAME_RE = re.compile(
    r"(?i)\b(меня зовут|мо[её] имя|это звонит|обращаться к вам|алло,? это)\s+"
    r"([А-ЯЁ][а-яё]{2,18}(?:\s+[А-ЯЁ][а-яё]{2,20})?)\b"
)

_COMPANY_RE = re.compile(
    r"\b(ООО|АО|ПАО|ЗАО|ИП|ЧП|УП|СП|МЧЖ)\s+(?:«[^»]{2,40}»|[А-ЯЁA-Z][\w\-]{2,30})\b"
)

# Префикс алиаса для структурного ID по типу сущности (register_id)
_ID_PREFIX = {
    "call": "CALL_#",
    "contact": "CONTACT_#",
    "deal": "DEAL_#",
    "thread": "THREAD_#",
    "company": "COMPANY_#",
    "user": "AGENT_",
    "ext": "EXT_",
}

_KIND_PREFIX = {
    "phone": "ТЕЛЕФОН",
    "email": "EMAIL",
    "card": "КАРТА",
    "passport": "ПАСПОРТ",
    "inn": "ИНН",
    "snils": "СНИЛС",
    "id_number_by": "ЛИЧНЫЙ_НОМЕР_РБ",
    "pinfl_uz": "ПИНФЛ_УЗ",
}


class PiiSanitizerConfig(BaseModel):
    """Состояние слайдера очистки ПДн (ТЗ v3.0 §4.2.2)."""

    enabled: bool = True
    strip_names: bool = True
    strip_phones_emails: bool = True
    strip_orders_contracts: bool = True
    strip_internal_ids: bool = True
    strip_company_names: bool = False
    custom_stop_words: list[str] = Field(default_factory=list)


@dataclass
class SanitizerSession:
    """Одна сессия очистки = один пакет (запрос preview/analyze или вызов
    MCP-тулза). Словарь (prefix, нормализованное значение) → alias даёт
    консистентные алиасы во всём пакете; alias_to_real — обратный маппинг
    для кликабельных ссылок на фронте (R-10)."""

    config: PiiSanitizerConfig | None = None
    aliases: dict[tuple[str, str], str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    stats: dict[str, int] = field(
        default_factory=lambda: {
            "names": 0,
            "phones_emails": 0,
            "orders_contracts": 0,
            "internal_ids": 0,
            "companies": 0,
        }
    )
    alias_to_real: dict[str, str] = field(default_factory=dict)
    _real_index: dict[str, str] = field(default_factory=dict)  # real.lower() → alias

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = PiiSanitizerConfig()

    # ── ядро алиасов ──

    def _get_alias(self, category: str, prefix: str, raw_value: str) -> str:
        norm = re.sub(r"\s+", " ", raw_value.strip()).lower()
        if prefix == "ТЕЛЕФОН":
            digits = re.sub(r"\D", "", raw_value)
            if len(digits) == 11 and digits.startswith("8"):
                digits = "7" + digits[1:]
            norm = digits or norm
        key = (prefix, norm)
        if key not in self.aliases:
            idx = self.counters.get(prefix, 0) + 1
            self.counters[prefix] = idx
            alias = f"[{prefix}_{idx}]"
            self.aliases[key] = alias
            self.alias_to_real[alias] = raw_value.strip()
        self.stats[category] = self.stats.get(category, 0) + 1
        return self.aliases[key]

    def register_internal_id(self, raw_id: str | None, prefix: str = "CALL_#") -> str | None:
        """Структурный ID (call/contact/deal/external) → [CALL_#N]. Реальный
        UUID регистрируется в _real_index: UUID в тексте заменяется тем же
        алиасом (кликабельные ссылки [CALL_#1] в отчёте LLM)."""
        if not raw_id:
            return None
        if not self.config.enabled or not self.config.strip_internal_ids:
            return str(raw_id)
        key = (prefix, str(raw_id).lower())
        if key not in self.aliases:
            idx = self.counters.get(prefix, 0) + 1
            self.counters[prefix] = idx
            alias = f"[{prefix}{idx}]"
            self.aliases[key] = alias
            self.alias_to_real[alias] = str(raw_id)
            self._real_index[str(raw_id).lower()] = alias
        self.stats["internal_ids"] = self.stats.get("internal_ids", 0) + 1
        return self.aliases[key]

    def register_id(self, kind: str, real_id: str | None) -> str | None:
        """Совместимая обёртка: register_id('call', uuid) → [CALL_#1]."""
        if real_id is None or real_id == "":
            return None
        return self.register_internal_id(str(real_id), _ID_PREFIX.get(kind, "ID_#"))

    def register_known_name(self, name: str | None) -> str | None:
        """Метаданные: display_name контакта / имя агента → [ФИО_N]."""
        if not name or not name.strip():
            return None
        if not self.config.enabled or not self.config.strip_names:
            return name
        return self._get_alias("names", "ФИО", name)

    def register_known_phone(self, phone: str | None) -> str | None:
        """Метаданные: phone_from/phone_to → [ТЕЛЕФОН_N] (тот же ключ, что у
        телефонов в тексте: +7/8-формы схлопываются по нормализованным цифрам)."""
        if not phone or not phone.strip():
            return None
        if not self.config.enabled or not self.config.strip_phones_emails:
            return phone
        return self._get_alias("phones_emails", "ТЕЛЕФОН", phone)

    def sanitize_value(self, value: str | None, category: str, label: str | None = None) -> str | None:
        """Структурное поле произвольной категории (коучинг: имя агента → [AGENT_N])."""
        if not value:
            return None
        if not self.config.enabled:
            return value
        if category == "phones_emails" and (label is None or label == "ТЕЛЕФОН"):
            return self.register_known_phone(value)
        if category == "names" and (label is None or label == "ФИО"):
            return self.register_known_name(value)
        if category == "internal_ids":
            return self.register_internal_id(value, label or "ID_#")
        prefix = label or {
            "orders_contracts": "ЗАКАЗ_ДОГОВОР",
            "companies": "КОМПАНИЯ",
        }.get(category, "ID_#")
        return self._get_alias(category, prefix, value)

    def sanitize_phone(self, phone: str | None) -> str | None:
        return self.register_known_phone(phone)

    # ── текст ──

    def sanitize_text(self, text: str) -> str:
        if not text or not self.config.enabled:
            return text
        out = text

        # 0) стоп-слова пользователя (Р-05: замена до остальных проходов)
        for custom in self.config.custom_stop_words:
            c_clean = custom.strip()
            if len(c_clean) >= 2:
                out = re.sub(
                    re.escape(c_clean),
                    lambda m: self._get_alias("names", "СКРЫТО", m.group(0)),
                    out,
                    flags=re.I,
                )

        # 1) спаны detect_pii (порядок детекторов = R-04) + UUID в тексте.
        #    Двухфазная замена: все спаны собираются на исходной строке,
        #    подстановка — с конца (R-05), плейсхолдеры не пере-матчатся.
        spans = list(detect_pii(out))
        if self.config.strip_internal_ids:
            taken = [(s.start, s.end) for s in spans]
            for m in _UUID_RE.finditer(out):
                if any(m.start() < e and st < m.end() for st, e in taken):
                    continue
                spans.append(
                    PIISpan(kind="uuid", start=m.start(), end=m.end(), value=m.group(0), detector="regex:uuid")
                )

        for sp in reversed(sorted(spans, key=lambda s: (s.start, s.end))):
            alias: str | None = None
            if sp.kind in ("phone", "email") and self.config.strip_phones_emails:
                alias = self._get_alias("phones_emails", _KIND_PREFIX[sp.kind], sp.value)
            elif sp.kind == "uuid" and self.config.strip_internal_ids:
                alias = self._real_index.get(sp.value.lower()) or self._get_alias(
                    "internal_ids", "ID_#", sp.value
                )
            elif sp.kind in ("card", "passport", "inn", "snils", "id_number_by", "pinfl_uz") and (
                self.config.strip_orders_contracts
            ):
                alias = self._get_alias("orders_contracts", _KIND_PREFIX[sp.kind], sp.value)
            if alias is None:
                continue
            out = out[: sp.start] + alias + out[sp.end :]

        # 2) номера заказов/договоров (ключевое слово сохраняется: «заказ [ЗАКАЗ_ДОГОВОР_1]»)
        if self.config.strip_orders_contracts:
            def _repl_order(m: re.Match) -> str:
                head, num = m.group(1), m.group(2)
                if num.startswith("[") and num.endswith("]"):
                    return m.group(0)
                alias = self._get_alias("orders_contracts", "ЗАКАЗ_ДОГОВОР", num)
                return f"{head} {alias}"

            out = _ORDER_CONTRACT_RE.sub(_repl_order, out)

        # 3) компании (опционально)
        if self.config.strip_company_names:
            out = _COMPANY_RE.sub(
                lambda m: self._get_alias("companies", "КОМПАНИЯ", m.group(0)),
                out,
            )

        # 4) ФИО (Фамилия Имя Отчество / Имя Отчество)
        if self.config.strip_names:
            out = _FIO_PATRONYMIC_RE.sub(
                lambda m: self._get_alias("names", "ФИО", m.group(0)),
                out,
            )

            # 5) имена-представления («меня зовут Ирина») — маркер сохраняется
            def _repl_intro(m: re.Match) -> str:
                lead, name_part = m.group(1), m.group(2)
                if name_part.startswith("["):
                    return m.group(0)
                alias = self._get_alias("names", "ФИО", name_part)
                return f"{lead} {alias}"

            out = _INTRO_NAME_RE.sub(_repl_intro, out)

        # 6) зарегистрированные имена метаданных в остатках текста
        return self.replace_known(out)

    def replace_known(self, text: str) -> str:
        """Замена уже зарегистрированных значений сессии (имена, компании) по
        словарю: display_name контакта и ФИО агента попадают в текст реплик."""
        if not self.config.enabled:
            return text
        for (prefix, _norm), alias in list(self.aliases.items()):
            if prefix not in ("ФИО", "КОМПАНИЯ"):
                continue
            real = self.alias_to_real.get(alias)
            if not real:
                continue
            pattern = re.compile(re.escape(real), re.IGNORECASE)
            text, n = pattern.subn(alias, text)
            category = "names" if prefix == "ФИО" else "companies"
            self.stats[category] = self.stats.get(category, 0) + n
        return text

    def sanitize_obj(self, obj: Any) -> Any:
        """Рекурсивная очистка dict/list/str (пакет данных для LLM)."""
        if isinstance(obj, str):
            return self.sanitize_text(obj)
        if isinstance(obj, dict):
            return {k: self.sanitize_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.sanitize_obj(v) for v in obj]
        return obj

    def summary(self) -> dict[str, Any]:
        """Статистика сессии для UI и llm_analysis_runs (ТЗ §4.2.3)."""
        return {
            "enabled": self.config.enabled,
            "total_redactions": sum(self.stats.values()),
            "by_category": dict(self.stats),
            "alias_map": dict(self.alias_to_real),
        }


# Совместимость с кодом, использующим прежнее имя класса
PiiSanitizer = SanitizerSession


def estimate_tokens(text: str) -> int:
    """Грубая оценка объёма контекста в токенах (ТЗ v3.0 §4.3, режим 3)."""
    return max(1, len(text) // 3) if text else 0
