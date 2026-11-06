"""Async-клиент OpenAI-compatible API (ТЗ v3.0 §4.1): OpenRouter, OpenAI,
Ollama / vLLM / LM Studio. Только httpx, без SDK-зависимостей."""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
REFERER = "https://polylog.local"
TITLE = "Polylog Speech Analytics"


class LLMError(RuntimeError):
    """Ошибка вызова внешнего LLM-эндпоинта (HTTP >= 400 или невалидный ответ)."""


def _headers(base_url: str, api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in base_url.lower():
        headers["HTTP-Referer"] = REFERER
        headers["X-Title"] = TITLE
    return headers


async def chat_completion(
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout_s: float = 180.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """POST {base_url}/chat/completions. Возвращает {text, usage, model}.
    transport — точка подмены для тестов (httpx.MockTransport)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=_headers(base_url, api_key),
                json=payload,
            )
    except httpx.HTTPError as e:
        raise LLMError(f"LLM-эндпоинт недоступен: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"LLM-эндпоинт вернул {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as e:
        raise LLMError("LLM-эндпоинт вернул не-JSON ответ") from e
    choices = data.get("choices") or []
    text = (choices[0].get("message") or {}).get("content", "") if choices else ""
    return {"text": text, "usage": data.get("usage") or {}, "model": data.get("model", model)}


async def list_models(
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str,
    timeout_s: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """GET {base_url}/models — список моделей с контекстом и ценами (у OpenRouter)."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models", headers=_headers(base_url, api_key)
            )
    except httpx.HTTPError as e:
        raise LLMError(f"LLM-эндпоинт недоступен: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"LLM-эндпоинт вернул {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else data
    out: list[dict[str, Any]] = []
    for m in items or []:
        out.append(
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "context_length": m.get("context_length"),
                "pricing": m.get("pricing"),
            }
        )
    return out
