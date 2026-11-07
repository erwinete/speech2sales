"""Автоматический скрипт приёмки ТЗ v5.0 (§9.3): все контуры V5-01..V5-03."""

import json
import sys
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polylog.export.scenario import build_trainer_scenario
from polylog.pii.detect import detect_pii
from polylog.pii.spoken_numbers import denormalize_spoken_numbers
from polylog.pipeline import compute_metrics

# 1. Проверка V5-01: денормализация проговоренных голосом паспортов и телефонов РФ, РБ и Узбекистана
spoken = (
    "Мой паспорт эм эр сто двадцать три сорок пять шестьдесят семь, "
    "а российский паспорт сорок пять десять сто двадцать три четыреста пятьдесят шесть, "
    "телефон плюс триста семьдесят пять двадцать девять сто одиннадцать двадцать два тридцать три"
)
denorm = denormalize_spoken_numbers(spoken)
spans = detect_pii(denorm)
assert sum(1 for s in spans if s.kind == "passport") >= 2, f"Голосовые паспорта РБ/РФ не распознаны: {denorm} -> {spans}"
assert any(s.kind == "phone" for s in spans), f"Голосовой телефон РБ не распознан: {denorm} -> {spans}"

# 2. Проверка V5-02: расширенные метрики речи (wpm, interruptions, longest_monologue_sec, sentiment_trajectory)
utts = [
    {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 6000, "text": "Добрый день компания Полилог меня зовут Иван удобно говорить?"},
    {"idx": 1, "speaker": "client", "start_ms": 5800, "end_ms": 10000, "text": "Не интересно, слишком дорого у вас."},
    {"idx": 2, "speaker": "agent", "start_ms": 10100, "end_ms": 20000, "text": "Понимаю, давайте сравним условия и я покажу демо?"},
    {"idx": 3, "speaker": "client", "start_ms": 20500, "end_ms": 25000, "text": "Хорошо, отлично, давайте посмотрим демо завтра."},
]
m = compute_metrics(utts)
assert "wpm" in m and "agent" in m["wpm"] and "client" in m["wpm"]
assert "interruptions" in m and m["interruptions"] >= 1
assert "longest_monologue_sec" in m
assert "sentiment_trajectory" in m

# 3. Проверка V5-03: валидация генератора TrainerScenario (Слой B) по JSON Schema
schema_path = Path(__file__).resolve().parents[2] / "schemas" / "trainer-scenario.schema.json"
schema = json.loads(schema_path.read_text(encoding="utf-8"))
dummy_scenario = build_trainer_scenario(
    call_id="01J9F2XQ7M5T8ZC3V6B0N4R8W1",
    objections=[{"type": "price", "span_text": "У вас слишком дорого", "response_span": "Давайте сравним условия и рассрочку"}],
    pii_policy="mask",
)
jsonschema.validate(instance=dummy_scenario, schema=schema)

# 4. Дополнительно: стадии диалога и текстовые упоминания (V5-02)
from polylog.nlp.stages import DIALOG_STAGES, detect_dialog_stages, extract_text_mentions  # noqa: E402

stages = detect_dialog_stages(utts)
assert stages and all(s["stage"] in DIALOG_STAGES or s["stage"] == "unclassified" for s in stages)
mentions = extract_text_mentions([
    {"idx": 0, "text": "Обсудили бюджет 500 тыс. руб., пришлите КП до завтра, ivan@mail.ru"},
])
kinds = {x["kind"] for x in mentions}
assert {"amount", "date", "email"} <= kinds, mentions

print("ALL V5.0 ARCHITECTURAL & FEATURE CHECKS PASSED!")
