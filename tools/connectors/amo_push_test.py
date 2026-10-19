"""Live push-тест amoCRM (явное «ок» пользователя, 2026-10-04): публикация звонка
в демо-CRM через POST /api/v4/calls + верификация ответа."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.ingest.amocrm import AmoCRMConnector, build_publish_body  # noqa: E402

env = {}
for line in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

conn = AmoCRMConnector(subdomain=env["AMOCRM_SUBDOMAIN"], access_token=env["AMOCRM_ACCESS_TOKEN"])

print("1. verify:", conn.verify())

uniq = f"polylog-live-{int(time.time())}"
body = build_publish_body(
    direction="outbound",
    duration_sec=312,
    phone="+79031112233",
    source="polylog",
    uniq=uniq,
    call_result="Тест интеграции «Полилог»: звонок обработан, скор 42/100",
)
print(f"2. POST /api/v4/calls (uniq={uniq})…")
res = conn.publish_call(body)
embedded = (res.get("_embedded") or {}).get("calls") or []
print("3. ответ amoCRM:")
print(json.dumps(res, ensure_ascii=False, indent=1)[:600])
if embedded:
    note_id = embedded[0].get("id")
    ent = (embedded[0].get("_embedded") or {}).get("entity") or {}
    print(f"4. звонок добавлен как примечание id={note_id}, привязан к сущности: {ent or 'карточка не найдена по номеру'}")
    print("   → проверь в amoCRM: сделка/контакт с телефоном +79031112233, новое примечание-звонок")
else:
    print("   ответ без _embedded — сверить вручную")
