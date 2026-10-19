from pathlib import Path

p = Path(r"F:\Z\rechevaua analitika\core\polylog\asr\diarize.py")
t = p.read_text(encoding="utf-8")

old = '''def assign_roles(turns: list[dict]) -> None:
    """Эвристика ролей: самый ранний активный спикер = агент (outbound-звонки
    начинают менеджеры; для inbound проверяется карта из коннектора — doc 02 §2.3).
    Мутирует turns, заменяя SPEAKER_XX на agent/client. Телефония = 2 роли:
    все прочие спикеры pyannote склеиваются в client."""
    speakers_by_first: dict[str, int] = {}
    for t in turns:
        speakers_by_first.setdefault(t["speaker"], t["start_ms"])
    ordered = sorted(speakers_by_first, key=lambda s: speakers_by_first[s])
    mapping = {s: ("agent" if i == 0 else "client") for i, s in enumerate(ordered)}
    for t in turns:
        t["speaker"] = mapping.get(t["speaker"], "client")'''
new = '''AGENT_SPEECH_MARKERS = re.compile(
    r"(компан\w+ |меня зовут|представля\w+|предлагаю|чем могу|наш\w* (продукт|сервис|услуг)"
    r"|бесплатн|демонстрац|давайте я покажу|у нас есть|готов\w+ (предложить|рассказать)"
    r"|я звоню (к вам|вам) с предложением)",
    re.I,
)


def pick_agent_speaker(
    speaker_texts: dict[str, str], first_speaker: str | None = None
) -> str | None:
    """Выбор агента по маркерам продающей речи (чистая функция, тесты без модели).
    text_score важнее порядка; при равенстве — первый активный."""
    if not speaker_texts:
        return None
    scores = {
        spk: len(AGENT_SPEECH_MARKERS.findall(text or ""))
        for spk, text in speaker_texts.items()
    }
    best = max(scores, key=lambda s: scores[s])
    if scores[best] > 0:
        return best
    return first_speaker


def assign_roles(turns: list[dict], texts_by_speaker: dict[str, str] | None = None) -> None:
    """Эвристика ролей: агент — спикер с маркерами продающей речи («меня зовут»,
    «представляю», «предлагаю»); при равенстве — первый активный (doc 02 §2.3).
    Мутирует turns, заменяя SPEAKER_XX на agent/client. Телефония = 2 роли:
    прочие спикеры pyannote склеиваются в client."""
    speakers_by_first: dict[str, int] = {}
    for t in turns:
        speakers_by_first.setdefault(t["speaker"], t["start_ms"])
    first_speaker = next(iter(speakers_by_first), None)

    agent: str | None = None
    if texts_by_speaker:
        agent = pick_agent_speaker(texts_by_speaker, first_speaker)
    if agent is None:
        agent = first_speaker

    mapping = {s: ("agent" if s == agent else "client") for s in speakers_by_first}
    for t in turns:
        t["speaker"] = mapping.get(t["speaker"], "client")'''
assert old in t, "assign_roles anchor"
t = t.replace(old, new, 1)

# импорт re
if "import re" not in t:
    t = t.replace("import logging\n", "import logging\nimport re\n", 1)

p.write_text(t, encoding="utf-8")
print("diarize.py: text-based role picking added")
