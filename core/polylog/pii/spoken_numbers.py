r"""Денормализация словесных числительных перед поиском ПДн (ТЗ v5.0 V5-01,
docs/02-modules.md §2.5). Клиенты диктуют голосом паспорта, телефоны, карты и
номера заказов («паспорт эм эр сто двадцать три …»); регулярки `\d+` такие
ПДн пропускают. Функция `denormalize_spoken_numbers(text)` сворачивает
последовательности русских числительных (2+ подряд числовых слов) в цифровые
строки и фонетические названия букв серий РБ/УЗ («эм эр» → «МР») — после неё
детекторы `_PHONE`, `_PASSPORT_*`, `_CARD`, `_ORDER_CONTRACT_RE` срабатывают."""

from __future__ import annotations

import re

_WORD_TO_VAL: dict[str, tuple[int, int]] = {
    # (значение, разрядность: 1=единицы/цифра, 2=десятки, 3=сотни)
    "ноль": (0, 1), "нуль": (0, 1),
    "один": (1, 1), "одна": (1, 1), "одну": (1, 1), "единица": (1, 1), "раз": (1, 1),
    "два": (2, 1), "две": (2, 1), "двойка": (2, 1),
    "три": (3, 1), "тройка": (3, 1),
    "четыре": (4, 1), "четверка": (4, 1), "четвёрка": (4, 1),
    "пять": (5, 1), "пятерка": (5, 1), "пятёрка": (5, 1),
    "шесть": (6, 1), "шестерка": (6, 1), "шестёрка": (6, 1),
    "семь": (7, 1), "семерка": (7, 1), "семёрка": (7, 1),
    "восемь": (8, 1), "восьмерка": (8, 1), "восьмёрка": (8, 1),
    "девять": (9, 1), "девятка": (9, 1),
    "десять": (10, 2),
    "одиннадцать": (11, 2), "двенадцать": (12, 2), "тринадцать": (13, 2),
    "четырнадцать": (14, 2), "пятнадцать": (15, 2), "шестнадцать": (16, 2),
    "семнадцать": (17, 2), "восемнадцать": (18, 2), "девятнадцать": (19, 2),
    "двадцать": (20, 2), "тридцать": (30, 2), "сорок": (40, 2),
    "пятьдесят": (50, 2), "шестьдесят": (60, 2), "семьдесят": (70, 2),
    "восемьдесят": (80, 2), "девяносто": (90, 2),
    "сто": (100, 3), "двести": (200, 3), "триста": (300, 3), "четыреста": (400, 3),
    "пятьсот": (500, 3), "шестьсот": (600, 3), "семьсот": (700, 3),
    "восемьсот": (800, 3), "девятьсот": (900, 3),
}

# Фонетические названия букв серий паспортов РБ и Узбекистана при диктовке по буквам
_SPOKEN_SERIES_MAP: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?i)\bэм\s+эр\b"), "МР"),
    (re.compile(r"(?i)\bэм\s+эс\b"), "МС"),
    (re.compile(r"(?i)\bа\s+бэ\b|\bа\s+вэ\b"), "АВ"),
    (re.compile(r"(?i)\bбэ\s+эм\b|\bвэ\s+эм\b"), "ВМ"),
    (re.compile(r"(?i)\bаш\s+бэ\b|\bэн\s+вэ\b"), "НВ"),
    (re.compile(r"(?i)\bка\s+аш\b|\bка\s+эн\b"), "КН"),
    (re.compile(r"(?i)\bка\s+бэ\b|\bка\s+вэ\b"), "КВ"),
    (re.compile(r"(?i)\bпэ\s+пэ\b|\bэр\s+эр\b"), "РР"),
    (re.compile(r"(?i)\bа\s+а\b"), "АА"),
    (re.compile(r"(?i)\bа\s+дэ\b"), "АД"),
    (re.compile(r"(?i)\bа\s+е\b"), "АЕ"),
    (re.compile(r"(?i)\bка\s+а\b"), "КА"),
    (re.compile(r"(?i)\bэф\s+а\b|\bфа\b"), "ФА"),
)


def _collapse_number_tokens(tokens: list[tuple[int, int]]) -> str:
    """Сворачивает последовательность (значение, разряд) в группы: «сто двадцать
    три» → 123; «сорок пять шестьдесят семь» → 45 67 (две цифровые группы)."""
    groups: list[int] = []
    cur_val = 0
    cur_rank = 0
    has_cur = False

    for val, rank in tokens:
        if not has_cur:
            cur_val = val
            cur_rank = rank
            has_cur = True
            if val == 0:
                groups.append(0)
                has_cur = False
            continue

        if cur_rank == 3 and rank == 2:
            cur_val += val
            cur_rank = 1 if 10 <= val <= 19 else 2
        elif cur_rank == 3 and rank == 1 and 1 <= val <= 9:
            cur_val += val
            cur_rank = 1
        elif cur_rank == 2 and cur_val >= 20 and rank == 1 and 1 <= val <= 9:
            cur_val += val
            cur_rank = 1
        else:
            groups.append(cur_val)
            cur_val = val
            cur_rank = rank
            if val == 0:
                groups.append(0)
                has_cur = False

    if has_cur:
        groups.append(cur_val)
    return " ".join(str(g) for g in groups)


_NUM_WORDS_PATTERN = "|".join(sorted(_WORD_TO_VAL.keys(), key=len, reverse=True))
_SEQ_RE = re.compile(
    rf"(?i)\b(?:плюс\s+)?(?:(?:{_NUM_WORDS_PATTERN}|\d+)[\s,\-]+)+(?:{_NUM_WORDS_PATTERN}|\d+)\b"
)


def denormalize_spoken_numbers(text: str) -> str:
    """Числительные словами (2+ подряд, разделители пробел/запятая/дефис) →
    цифровые группы; «плюс …» → «+…» (телефон). Фонетические серии («эм эр»)
    заменяются раньше, чтобы паспорт РБ собрался в один токен."""
    if not text:
        return text
    out = text
    for pat, repl in _SPOKEN_SERIES_MAP:
        out = pat.sub(repl, out)

    def _repl(m: re.Match) -> str:
        chunk = m.group(0)
        has_plus = chunk.lower().lstrip().startswith("плюс")
        words = re.findall(r"[А-Яа-яЁё]+|\d+", chunk)
        parsed: list[tuple[int, int]] = []
        word_hits = 0
        for w in words:
            wl = w.lower().replace("ё", "е")
            if wl == "плюс":
                continue
            if w.isdigit():
                parsed.append((int(w), 1))
            elif wl in _WORD_TO_VAL:
                parsed.append(_WORD_TO_VAL[wl])
                word_hits += 1
            elif w.lower() in _WORD_TO_VAL:
                parsed.append(_WORD_TO_VAL[w.lower()])
                word_hits += 1
            else:
                return chunk
        if word_hits == 0 or len(parsed) < 2:
            return chunk
        digits_str = _collapse_number_tokens(parsed)
        return f"+{digits_str}" if has_plus else digits_str

    return _SEQ_RE.sub(_repl, out)
