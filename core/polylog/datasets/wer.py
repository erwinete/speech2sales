"""WER-харнесс (doc 02 §9, doc 06 §6): нормализация русской речи + WER по Левенштейну.

Чистый Python без зависимостей — работает и в CI, и на стенде.
Используется tools/datasets/benchmark_asr.py (приёмочная S5).
"""

import re

_PUNCT = re.compile(r"[^\w\s]", re.I)
_SPACES = re.compile(r"\s+")


def normalize_ru(text: str) -> list[str]:
    """Нижний регистр, ё→е, без пунктуации; числа остаются словами-токенами."""
    t = (text or "").lower().replace("ё", "е")
    t = _PUNCT.sub(" ", t)
    return _SPACES.sub(" ", t).strip().split()


def _levenshtein(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    """Word Error Rate = (sub + del + ins) / len(ref_words). Пустой эталон → 0/1."""
    r, h = normalize_ru(ref), normalize_ru(hyp)
    if not r:
        return 0.0 if not h else 1.0
    return _levenshtein(r, h) / len(r)


def wer_detail(ref: str, hyp: str) -> dict:
    """Разложение на substitutions/deletions/insertions (для отчёта S5)."""
    r, h = normalize_ru(ref), normalize_ru(hyp)
    n, m = len(r), len(h)
    if not r:
        return {"wer": 0.0 if not h else 1.0, "sub": 0, "del": 0, "ins": len(h), "ref_words": 0}
    # DP с обратным ходом
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    sub = dele = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (r[i - 1] != h[j - 1]):
            if r[i - 1] != h[j - 1]:
                sub += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dele += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return {"wer": d[n][m] / n, "sub": sub, "del": dele, "ins": ins, "ref_words": n}
