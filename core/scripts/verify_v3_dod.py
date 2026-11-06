"""Автоматический верификатор выполнения ТЗ v3.0 (РФ, РБ, Узбекистан).

Запуск перед финальным коммитом (§8.4 DoD):
    cd core && ..\\.venv\\Scripts\\python.exe scripts\\verify_v3_dod.py
Если хотя бы один assert падает — коммит считается незавершённым.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polylog.pii.detect import detect_pii
from polylog.pii.sanitizer import PiiSanitizerConfig, SanitizerSession

# 1. Проверка распознавания паспортов и гос. идентификаторов РФ, РБ (Беларусь) и Узбекистана
# 1.1 Паспорт РФ (10 цифр) и телефон РФ (+7)
ru_spans = detect_pii("Паспорт РФ: 45 10 123456 выдан УФМС, тел +7 (903) 123-45-67")
assert any(s.kind == "passport" and "123456" in s.value for s in ru_spans), "Паспорт РФ 45 10 123456 не распознан!"
assert any(s.kind == "phone" for s in ru_spans), "Телефон РФ не распознан!"

# 1.2 Паспорт РБ (серия MP/HB/AB + 7 цифр и личный номер РБ 14 символов) и телефон РБ (+375)
by_spans = detect_pii("Паспорт РБ: MP 1234567 (кириллицей МР 7654321), личный номер 3120585A012PB5, тел +375 29 123-45-67")
assert sum(1 for s in by_spans if s.kind == "passport") == 2, f"Паспорта РБ (латиница + кириллица) не распознаны: {by_spans}"
assert any(s.kind == "id_number_by" for s in by_spans), "Личный номер РБ (14 симв.) не распознан!"
assert any(s.kind == "phone" and "375" in s.value for s in by_spans), "Телефон РБ +375 не распознан!"

# 1.3 Паспорт/ID Республики Узбекистан (серия AA/AD/KA/FA + 7 цифр и ПИНФЛ 14 цифр) и телефон УЗ (+998)
uz_spans = detect_pii("Паспорт РУз: AA 1234567, загран FA7654321, ПИНФЛ 31504901234567, тел +998 90 123-45-67")
assert sum(1 for s in uz_spans if s.kind == "passport") == 2, f"Паспорта Узбекистана (AA и FA) не распознаны: {uz_spans}"
assert any(s.kind == "pinfl_uz" for s in uz_spans), "ПИНФЛ Узбекистана (14 цифр) не распознан!"
assert any(s.kind == "phone" and "998" in s.value for s in uz_spans), "Телефон Узбекистана +998 не распознан!"

# 2. Проверка работы слайдера очистки ПДн (ФИО, телефон, заказ, паспорта РФ/РБ/УЗ)
sess = SanitizerSession(PiiSanitizerConfig(enabled=True))
sample = (
    "Добрый день, меня зовут Сергей Петрович, заказ № 48912-А, "
    "паспорт РФ 45 10 123456, паспорт РБ MP1234567, паспорт УЗ AA7654321, "
    "тел +7 (903) 123-45-67, +375 29 999-88-77, +998 90 555-44-33."
)
cleaned = sess.sanitize_text(sample)
assert "Сергей Петрович" not in cleaned and "[ФИО_" in cleaned, "ФИО не было очищено санитайзером!"
assert "48912-А" not in cleaned and "[ЗАКАЗ_ДОГОВОР_" in cleaned, "Номер заказа не был очищен!"
assert cleaned.count("[ПАСПОРТ_") == 3, f"Не все 3 паспорта (РФ, РБ, УЗ) очищены: {cleaned}"
assert cleaned.count("[ТЕЛЕФОН_") == 3, f"Не все 3 телефона (РФ, РБ, УЗ) очищены: {cleaned}"

# 3. Проверка регистрации коннектора sql-cdr (BUG-08)
from polylog.ingest.registry import get_connector

conn = get_connector("sql-cdr", {"dsn": "sqlite:///:memory:"})
assert conn is not None, "BUG-08 НЕ ИСПРАВЛЕН: sql-cdr не зарегистрирован в registry.py!"

print("ALL V3.0 CORE CHECKS (INCLUDING RU/BY/UZ PASSPORTS & PHONES) PASSED!")
