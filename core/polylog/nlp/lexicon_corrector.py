"""L1-словарная коррекция (doc 02 §3.2): исправление частых ошибок ASR
по доменному словарю организации (`lexicon_entries`).

Логика: для каждой активной записи — точные вхождения `aliases` (с учётом
`case_sensitive`) заменяются каноническим `term`; нечёткие совпадения —
difflib.SequenceMatcher, порог 0.86. Исходный текст сохраняется в
`seg.raw_text`, `seg.corrected = True` при наличии замен. Вызывается из
stage_postprocess до детекции ПДн."""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.models.system import LexiconEntry

log = logging.getLogger("polylog.nlp.lexicon")

FUZZY_THRESHOLD = 0.86
# слова длиной от 4 символов — кандидаты на нечёткое сопоставление
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё_]{4,}")


@dataclass
class LexiconRule:
    """Подготовленное правило замены одной записи словаря."""

    term: str
    aliases: list[str]
    case_sensitive: bool
    phonetic_key: str | None
    # варианты написания: канонический термин + алиасы
    variants: list[str] = field(default_factory=list)


def _build_rules(entries: list) -> list[LexiconRule]:
    rules: list[LexiconRule] = []
    for e in entries:
        aliases = list(e.aliases or [])
        variants = [e.term, *aliases]
        variants = [v for v in dict.fromkeys(v.strip() for v in variants) if v]
        rules.append(
            LexiconRule(
                term=e.term,
                aliases=aliases,
                case_sensitive=bool(e.case_sensitive),
                phonetic_key=e.phonetic_key,
                variants=variants,
            )
        )
    # сначала длинные варианты (чтобы «полилог про» не съел «полилог»)
    rules.sort(key=lambda r: -max(len(v) for v in r.variants))
    return rules


def _apply_exact(text: str, rule: LexiconRule) -> tuple[str, int]:
    count = 0
    for variant in sorted(rule.variants, key=len, reverse=True):
        if variant == rule.term:
            continue
        if rule.case_sensitive:
            pattern = re.compile(re.escape(variant))
        else:
            pattern = re.compile(re.escape(variant), re.IGNORECASE)
        text, n = pattern.subn(rule.term, text)
        count += n
    return text, count


def _apply_fuzzy(text: str, rule: LexiconRule) -> tuple[str, int]:
    """Нечёткая замена слов по SequenceMatcher (порог 0.86) к каноническому
    термину и алиасам. Работает по словам, регистронезависимо."""
    if not rule.term or len(rule.term) < 4:
        return text, 0
    targets = [rule.term.lower(), *(a.lower() for a in rule.aliases)]
    count = 0
    out: list[str] = []
    pos = 0
    for m in _WORD_RE.finditer(text):
        out.append(text[pos : m.start()])
        word = m.group(0)
        low = word.lower()
        best = max(difflib.SequenceMatcher(None, low, t).ratio() for t in targets)
        if best >= FUZZY_THRESHOLD and low != rule.term.lower():
            out.append(rule.term)
            count += 1
        else:
            out.append(word)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), count


async def load_rules(session: AsyncSession, org_id) -> list[LexiconRule]:
    entries = (
        (
            await session.execute(
                select(LexiconEntry).where(
                    LexiconEntry.org_id == org_id, LexiconEntry.enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    return _build_rules(list(entries))


def apply_to_segments(rules: list[LexiconRule], segments: list) -> int:
    """In-place коррекция ORM-сегментов (CallSegment). Возвращает число
    исправленных сегментов. raw_text хранит исходный текст первой правки."""
    if not rules:
        return 0
    fixed = 0
    for seg in segments:
        original = seg.text or ""
        text = original
        total = 0
        for rule in rules:
            text, n = _apply_exact(text, rule)
            total += n
            if n:
                text, n = _apply_fuzzy(text, rule)
                total += n
        if total and text != original:
            if not seg.raw_text:
                seg.raw_text = original
            seg.text = text
            seg.corrected = True
            fixed += 1
    return fixed


async def apply_lexicon_correction(
    session: AsyncSession, org_id, segments: list
) -> int:
    """Загрузить правила организации и применить к сегментам. Для тестов без
    правил — пустой список, сегменты не трогаются."""
    rules = await load_rules(session, org_id)
    return apply_to_segments(rules, segments)
