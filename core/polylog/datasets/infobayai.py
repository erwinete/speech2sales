"""Клиент и парсинг строк InfoBayAI через datasets-server API (doc 06 §1.1).

Токен никогда не логируется; читается из env HF_TOKEN или .env проекта.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

DATASET_SINGLE = "InfoBayAI/Russian-Call-Center-Audio-Dataset-Single-Channel"
DATASET_DUAL = "InfoBayAI/Russian_Call_Center_Audio_Dataset_Dual_Channel"

TRANSCRIPT_CANDIDATES = (
    "transcript", "text", "sentence", "utterance", "answer", "target", "label_text", "words"
)
AUDIO_CANDIDATES = ("audio", "speech", "wav", "recording", "file", "audio_file")


def load_token(explicit: str | None = None) -> str | None:
    """HF_TOKEN: аргумент → env → .env проекта (не логируется)."""
    if explicit:
        return explicit
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^HF_TOKEN=(\S+)$", line.strip())
            if m:
                return m.group(1)
    return None


def auth_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def get_splits(token: str | None, dataset: str = DATASET_SINGLE) -> dict[str, Any]:
    url = f"https://datasets-server.huggingface.co/splits?dataset={quote(dataset, safe='')}"
    r = httpx.get(url, headers=auth_headers(token), timeout=30)
    r.raise_for_status()
    return r.json()


def get_rows(
    token: str | None,
    dataset: str = DATASET_SINGLE,
    config: str = "default",
    split: str = "train",
    offset: int = 0,
    length: int = 100,
) -> dict[str, Any]:
    url = (
        "https://datasets-server.huggingface.co/rows"
        f"?dataset={quote(dataset, safe='')}&config={config}&split={split}"
        f"&offset={offset}&length={length}"
    )
    r = httpx.get(url, headers=auth_headers(token), timeout=60)
    r.raise_for_status()
    return r.json()


def extract_audio(row: dict[str, Any]) -> tuple[str | None, str | None, bytes | None]:
    """Ищет аудио-поле → (url, path, bytes).

    Формат InfoBayAI (проверено 2026-10-03): audio = [ {src: <resolve-URL>, type: "audio/wav"} ].
    Поддерживаем и стандартный shape {url/path/bytes}.
    """
    for key in AUDIO_CANDIDATES:
        if key not in row:
            continue
        v = row[key]
        if isinstance(v, list) and v and isinstance(v[0], dict):
            v = v[0]  # InfoBayAI: список с одним элементом-ссылкой
        if isinstance(v, dict):
            url = v.get("src") or v.get("url")
            path = v.get("path") or (url.rsplit("/", 1)[-1] if url else None)
            return url, path, v.get("bytes")
        if isinstance(v, str) and (v.startswith("http") or v.endswith((".wav", ".mp3", ".ogg"))):
            return v, v.rsplit("/", 1)[-1], None
    return None, None, None


def extract_transcript(row: dict[str, Any]) -> tuple[str | None, str]:
    """Ищет текстовый столбец с транскриптом → (значение, имя_колонки)."""
    for key in TRANSCRIPT_CANDIDATES:
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip(), key
    # fallback: первая строка > 20 символов, не похожая на путь/id
    for key, v in row.items():
        if isinstance(v, str) and len(v) > 20 and not v.startswith(("http", "/")):
            return v.strip(), key
    return None, ""


def sidecar_from_row(text: str | None, duration_ms: int = 0) -> list[dict[str, Any]]:
    """Sidecar для stub-ASR (doc 09 §3): одна реплика, спикер неизвестен (single-channel)."""
    if not text:
        return []
    return [{"speaker": "unknown", "start_ms": 0, "end_ms": max(0, duration_ms), "text": text}]


def download_audio(url: str, token: str | None) -> bytes:
    r = httpx.get(url, headers=auth_headers(token), timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.content
