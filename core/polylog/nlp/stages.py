"""Стадии диалога и текстовые упоминания (V5-02, ТЗ v5.0 §9.2-2).

- detect_dialog_stages: разметка звонка по 8 каноническим стадиям (`greeting` …
  `goodbye`) на основе лексиконов ключевых слов; результат сохраняется в
  `CallMetrics.metrics["stages"]` и экспортируется в поле `stages` CallArtifact.
- extract_text_mentions: извлечение сумм/бюджетов, дат/сроков, email и телефонов
  из текста реплик для таблицы `TextMention` (заполнение в stage_analyze).
"""

from __future__ import annotations

import re

# 8 канонических стадий по порядку скрипта продаж (schemas/call-artifacts.schema.json)
DIALOG_STAGES = (
    "greeting",
    "identification",
    "qualification",
    "presentation",
    "objection_handling",
    "negotiation",
    "closing",
    "goodbye",
)

# Лексиконы стадий: совпадение ключевого слова в реплике — кандидат на стадию
_STAGE_LEXICON: dict[str, re.Pattern] = {
    "greeting": re.compile(
        r"(?i)\b(добрый (день|вечер)|здравствуйте|алло|приветствую|компания \S+)"
    ),
    "identification": re.compile(
        r"(?i)\b(меня зовут|моё имя|мое имя|как я могу|кто у телефона|я (звоню|представляю))"
    ),
    "qualification": re.compile(
        r"(?i)\b(какими объёмами|сколько (у вас|вас)|какой у вас|что используете|"
        r"расскажите о (задач|потребн)|подходит ли|какие требования|с какими вопросами)"
    ),
    "presentation": re.compile(
        r"(?i)\b(наш (продукт|сервис)|мы предлагаем|позвольте (показать|рассказать)|"
        r"демонстраци|демо|покажу|ознаком[иь]?тесь|наши условия|тариф)"
    ),
    "objection_handling": re.compile(
        r"(?i)\b(дорого|дороговато|не интересно|у нас уже есть|подумаю|"
        r"отправьте (кп|предложение)|конкурент|времени нет|нет бюджета|не сейчас)"
    ),
    "negotiation": re.compile(
        r"(?i)\b(скидк|рассрочк|условия (оплаты|договор)|сможем (сделать|обсудить)|"
        r"давайте (сравним|обсудим)|цена (за|на)|коммерческое предложение)"
    ),
    "closing": re.compile(
        r"(?i)\b(отправим (счёт|кп|договор)|подписываем|договоримся|начнём|начнем|"
        r"когда (можем|удобно) (начать|перейти)|выставлю (счёт|счет)|оформля[еи]м|подтверждаете)"
    ),
    "goodbye": re.compile(
        r"(?i)\b(до свидания|всего доброго|хорошего дня|спасибо за (звонок|время)|"
        r"буду ждать|свяжемся|до связи|пока)"
    ),
}

# ── извлечение сущностей ──

_AMOUNT_RE = re.compile(
    r"(?i)\b(\d[\d\s.,]{0,12})\s*(тыс\.?|тысяч[аи]?|млн\.?|миллион[аов]?|руб\.?|рублей|бакс[аов]?|\$)\b"
    r"|\$\s*(\d[\d\s.,]{0,12})"
)
_DATE_RE = re.compile(
    r"(?i)\b(завтра|послезавтра|сегодня|в понедельник|во вторник|в среду|в четверг|в пятниц[уаю]|"
    r"до \d{1,2}\s*числа|\d{1,2}\s+(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|"
    r"сентябр|октябр|ноябр|декабр)\w*|через (?:неделю|два дня|пять дней|месяц|\d+ дней?))\b"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+7|8|\+375|\+998)[\s\-(]*\d{2,3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")


def detect_dialog_stages(segments: list[dict]) -> list[dict]:
    """Разметка реплик по стадиям. Алгоритм:
    1) реплика с ключевым словом стадии → кандидат (стадия идёт от предыдущего
       кандидата до конца реплики текущего);
    2) хвост после последнего кандидата помечается unclassified; звонок без
       единого ключевого слова возвращается одним интервалом unclassified."""
    if not segments:
        return []
    candidates: list[tuple[str, int]] = []  # (stage, segment_idx)
    for i, s in enumerate(segments):
        text = s.get("text") or ""
        for stage in DIALOG_STAGES:
            if _STAGE_LEXICON[stage].search(text):
                candidates.append((stage, i))
    if not candidates:
        return [
            {
                "stage": "unclassified",
                "start_ms": segments[0]["start_ms"],
                "end_ms": segments[-1]["end_ms"],
            }
        ]

    out: list[dict] = []
    prev_idx = 0
    for stage, idx in candidates:
        out.append({
            "stage": stage,
            "start_ms": segments[prev_idx]["start_ms"],
            "end_ms": segments[idx]["end_ms"],
        })
        prev_idx = idx
    if prev_idx < len(segments) - 1:
        out.append({
            "stage": "unclassified",
            "start_ms": segments[prev_idx]["start_ms"],
            "end_ms": segments[-1]["end_ms"],
        })
    return out


def extract_text_mentions(segments: list[dict]) -> list[dict]:
    """Сущности из реплик: amount (суммы), date (даты/сроки), email, phone.
    Выход — заготовки строк TextMention (V5-02)."""
    mentions: list[dict] = []
    for s in segments:
        text = s.get("text") or ""
        idx = s.get("idx")
        for kind, pattern in (
            ("amount", _AMOUNT_RE),
            ("date", _DATE_RE),
            ("email", _EMAIL_RE),
            ("phone", _PHONE_RE),
        ):
            for m in pattern.finditer(text):
                mentions.append({
                    "segment_idx": idx,
                    "kind": kind,
                    "value": m.group(0).strip(),
                })
    return mentions
