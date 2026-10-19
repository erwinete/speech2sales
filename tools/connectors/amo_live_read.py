"""Live amoCRM: verify + чтение контактов/сделок через исправленный коннектор."""

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.ingest.amocrm import AmoCRMConnector  # noqa: E402


async def main() -> None:
    env = {}
    env_file = Path(__file__).resolve().parents[2] / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()

    conn = AmoCRMConnector(subdomain=env.get("AMOCRM_SUBDOMAIN", "demo"),
                           access_token=env.get("AMOCRM_ACCESS_TOKEN", ""))

    def run_sync(fn, **kw):
        # httpx.Client — sync; коннектор синхронный, вызываем напрямую
        return fn(**kw)

    check = conn.verify()
    print("verify:", check)
    if not check.get("ok"):
        sys.exit(1)

    contacts = conn.get_contacts(limit=5)
    print(f"контакты: {len(contacts)}")
    for c in contacts[:3]:
        phones = []
        for cf in c.get("custom_fields_values") or []:
            if cf.get("field_code") == "PHONE":
                phones = [v.get("value") for v in cf.get("values", [])]
        print(f"  #{c['id']} {c.get('name')} тел: {phones or '—'}")

    leads = conn.get_leads(limit=5)
    print(f"сделки: {len(leads)}")
    for ld in leads[:3]:
        print(f"  #{ld['id']} {ld.get('name')} | цена {ld.get('price')}")


asyncio.run(main())
