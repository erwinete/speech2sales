"""Ингест и коннекторы (doc 02 §1)."""

from polylog.ingest.base import CallMeta, CallRef, ConnectorError, TelephonyConnector
from polylog.ingest.registry import get_connector

__all__ = [
    "CallMeta",
    "CallRef",
    "ConnectorError",
    "TelephonyConnector",
    "get_connector",
]
