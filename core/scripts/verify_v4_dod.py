"""Автоматический верификатор ТЗ v4.0 (§8.4, DEF-01..DEF-05).

Запуск перед финальным коммитом:
    cd core && ..\\.venv\\Scripts\\python.exe scripts\\verify_v4_dod.py
Если хотя бы один assert падает — коммит считается незавершённым.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polylog.graph.service import normalize_phone
from polylog.pii.detect import detect_pii
from polylog.pii.sanitizer import PiiSanitizerConfig, SanitizerSession

# 1. Проверка DEF-01: нормализация телефонов РФ, Беларуси и Узбекистана в графе контактов
assert normalize_phone("8 (903) 123-45-67") == "+79031234567"
assert normalize_phone("+375 (29) 123-45-67") == "+375291234567"
assert normalize_phone("8 029 123-45-67") == "+375291234567"
assert normalize_phone("8 017 222-33-44") == "+375172223344"
assert normalize_phone("998 90 123-45-67") == "+998901234567"

# 2. Проверка DEF-02: паспорта и личные номера РФ, РБ и Узбекистана (включая шумную ASR-разбивку)
spans_ru = detect_pii("Паспорт РФ 45 10 123 456 и второй 4510 654321")
assert sum(1 for s in spans_ru if s.kind == "passport") == 2

spans_by = detect_pii("Паспорт РБ MP 1234567, кириллицей МР 123 45 67, личный номер 3120585A012PB5")
assert sum(1 for s in spans_by if s.kind == "passport") == 2
assert any(s.kind == "id_number_by" for s in spans_by)

spans_uz = detect_pii("Паспорт РУз AA 1234567, кириллицей АД 765 43 21, ПИНФЛ 31504901234567")
assert sum(1 for s in spans_uz if s.kind == "passport") == 2
assert any(s.kind == "pinfl_uz" for s in spans_uz)

# 3. Проверка санитайзера и обратного словаря alias_map (DEF-05)
sess = SanitizerSession(PiiSanitizerConfig(enabled=True))
call_alias = sess.register_internal_id("11111111-2222-3333-4444-555555555555", prefix="CALL_#")
text_out = sess.sanitize_text("Меня зовут Иван Петрович Сидоров, заказ № 7781-Б, паспорт MP1234567, тел 8 029 555-44-33")
summary = sess.summary()
assert call_alias == "[CALL_#1]" and summary["alias_map"]["[CALL_#1]"] == "11111111-2222-3333-4444-555555555555"
assert "[ФИО_1]" in text_out and "[ЗАКАЗ_ДОГОВОР_1]" in text_out and "[ПАСПОРТ_1]" in text_out and "[ТЕЛЕФОН_1]" in text_out

# 4. Проверка MCP-полноты (DEF-04): методы сервера
import asyncio

from polylog.mcp.server import handle_rpc  # noqa: E402

rpc = lambda method, params=None: asyncio.run(  # noqa: E731
    handle_rpc({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, None, None, {})
)
assert len(rpc("resources/list")["result"]["resources"]) == 4
assert len(rpc("prompts/list")["result"]["prompts"]) == 5
assert rpc("ping")["result"] == {}
assert asyncio.run(
    handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, None, None, {})
) is None  # уведомления без ответа

# 5. Проверка бюджета токенов и smart_compress (DEF-03)
from polylog.llm.client import LLM_TIMEOUT  # noqa: E402
from polylog.llm.context_builder import _compress_dialogue  # noqa: E402

segments = [{"text": f"реплика номер {i}"} for i in range(40)]
kept, dropped = _compress_dialogue(segments, key_texts=["реплика номер 20"])
assert 0 < len(kept) < 40 and dropped > 0
assert any("реплика номер 20" in s["text"] for s in kept), "ключевая реплика потеряна"
assert LLM_TIMEOUT.read >= 180.0

print("ALL V4.0 DEEP AUDIT CHECKS PASSED!")
