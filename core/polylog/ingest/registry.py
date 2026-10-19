"""Реестр коннекторов (plugin-граница ADR-10: сторонние коннекторы подключаются тут)."""

from typing import Any

from polylog.ingest.base import CallRef, ConnectorError


class _WebhookOnly:
    """Коннекторы с чисто webhook-моделью (Битрикс24): discover не нужен —
    события приходят на POST /api/v1/hooks/{kind} и парсятся на входе."""

    def __init__(self, kind: str, parse_fn) -> None:
        self.id = kind
        self._parse = parse_fn

    def parse(self, payload: dict) -> CallRef | None:
        return self._parse(payload)

    def verify(self) -> dict:
        return {"ok": True, "mode": "webhook"}


def get_connector(kind: str, config: dict[str, Any]):
    if kind in ("freepbx", "devstand"):
        from polylog.ingest.freepbx import FreePBXConnector

        # dev-стенд эмулирует FreePBX-артефакты (doc 09 §2)
        return FreePBXConnector(monitor_dir=config.get("monitor_dir", "./data/monitor"))
    if kind == "cisco_ucm":
        from polylog.ingest.cisco_ucm import CiscoUCMConnector

        return CiscoUCMConnector(cdr_dir=config.get("cdr_dir", "./data/cisco-cdr"))
    if kind == "oktell":
        from polylog.ingest.oktell import OktellConnector

        return OktellConnector(config=config)
    if kind == "mightycall":
        from polylog.ingest.mightycall import MightyCallConnector

        return MightyCallConnector(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", "https://api.mightycall.io/v1"),
        )
    if kind == "bitrix24":
        from polylog.ingest.bitrix24 import Bitrix24Connector, parse_event_payload

        # portal+ключ → pull-клиент voximplant.statistic.get; иначе webhook-only
        if config.get("portal"):
            return Bitrix24Connector(
                portal=config["portal"],
                user_id=config.get("user_id", "1"),
                webhook_key=config.get("webhook_key", ""),
                oauth_token=config.get("oauth_token", ""),
            )
        return _WebhookOnly("bitrix24", parse_event_payload)
    if kind == "amocrm":
        from polylog.ingest.amocrm import AmoCRMConnector

        return AmoCRMConnector(
            subdomain=config.get("subdomain", ""),
            access_token=config.get("access_token", ""),
        )
    if kind == "sftp-monitor":
        from polylog.ingest.live import SftpConfig, SftpMonitorConnector, sftp_config_from_env

        # база — env (POLYLOG_SFTP_*); dict-конфиг переопределяет поля
        cfg = sftp_config_from_env()
        if config.get("host"):
            cfg = SftpConfig(
                host=config["host"],
                username=config.get("username", cfg.username),
                password=config.get("password", cfg.password),
                port=int(config.get("port", cfg.port)),
                key_path=config.get("key_path", cfg.key_path),
                remote_dir=config.get("remote_dir", cfg.remote_dir),
                pattern=config.get("pattern", cfg.pattern),
                name_regex=config.get("name_regex", cfg.name_regex),
            )
        return SftpMonitorConnector(cfg)
    raise ConnectorError(
        f"коннектор {kind!r} не зарегистрирован; доступно: freepbx, devstand, cisco_ucm, "
        f"oktell, mightycall, bitrix24 (webhook), amocrm"
    )
