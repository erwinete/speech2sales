#!/usr/bin/env python3
"""OAuth-авторизация в amoCRM (для демо-аккаунта demo.amocrm.ru и любых других).

Два пути (официальная схема amoCRM):

A) **Long-lived токен** (проще всего): в интерфейсе amoCRM → Настройки →
   Интеграции → создать внешнюю приватную интеграцию → скопировать long-lived
   токен → вставить сюда (--token) или в .env (AMOCRM_ACCESS_TOKEN).

B) **Полный OAuth** (--client-id --client-secret): создать интеграцию с
   redirect_uri = https://polylog.local/oauth/amocrm (или своим), затем:
   1. Скрипт печатает authorize URL — открыть в браузере под демо-аккаунтом.
   2. amoCRM перебросит на redirect_uri с ?code=... и (mode=post_message) —
      скопировать код из адресной строки.
   3. Вставить код сюда → скрипт обменяет на access/refresh и допишет в .env.

Проверка: GET /api/v4/account с полученным токеном.
Пароль пользователя (example@mail.ru) в API v4 не используется — только токены.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.ingest.amocrm import AmoOAuth, AmoCRMConnector  # noqa: E402

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def save_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    lines = [l for l in lines if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subdomain", default="demo")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    ap.add_argument("--code", default="", help="код из redirect после authorize URL")
    ap.add_argument("--token", default="", help="готовый long-lived токен (путь A)")
    args = ap.parse_args()

    token = args.token
    refresh = ""
    if not token:
        if not (args.client_id and args.client_secret):
            print("Укажите --client-id/--client-secret (путь B) или --token (путь A)", file=sys.stderr)
            sys.exit(2)
        oauth = AmoOAuth(args.client_id, args.client_secret)
        if not args.code:
            print("1. Открой в браузере (под демо-аккаунтом):\n")
            print("   " + oauth.authorize_url(args.subdomain))
            print("\n2. После согласия скопируй ?code=... из адресной строки redirect")
            print("3. Запусти: python amocrm_oauth.py --code <КОД> --client-id ... --client-secret ...")
            return
        tokens = oauth.exchange_code(args.subdomain, args.code)
        token = tokens.get("access_token", "")
        refresh = tokens.get("refresh_token", "")
        print(f"access_token получен (expires_in={tokens.get('expires_in')})")

    client = AmoCRMConnector(subdomain=args.subdomain, access_token=token)
    check = client.verify()
    print(f"проверка /api/v4/account: {check}")
    if not check.get("ok"):
        print("токен не принят — проверить интеграцию/права", file=sys.stderr)
        sys.exit(1)

    save_env("AMOCRM_SUBDOMAIN", args.subdomain)
    save_env("AMOCRM_ACCESS_TOKEN", token)
    if refresh:
        save_env("AMOCRM_REFRESH_TOKEN", refresh)
    print(f"сохранено в {ENV_PATH}: AMOCRM_SUBDOMAIN, AMOCRM_ACCESS_TOKEN"
          + (", AMOCRM_REFRESH_TOKEN" if refresh else ""))


if __name__ == "__main__":
    main()
