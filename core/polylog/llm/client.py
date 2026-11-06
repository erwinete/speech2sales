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

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# R-11 (ТЗ v3.0 §8.1): reasoning-модели отвечают 40-90 сек — read 180 с.
LLM_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

_STATUS_HINTS = {
    401: "неверный или просроченный API-ключ",
    402: "недостаточно кредитов на аккаунте провайдера",
    429: "превышен лимит запросов (rate limit) — попробуйте позже",
}


def _llm_error(status: int, body: str) -> LLMError:
    hint = _STATUS_HINTS.get(status, f"HTTP {status}")
    return LLMError(f"LLM-эндпоинт: {hint} ({status}): {body[:200]}", status_code=status)


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
    timeout: httpx.Timeout | None = None,
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
        async with httpx.AsyncClient(timeout=timeout or LLM_TIMEOUT, transport=transport) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=_headers(base_url, api_key),
                json=payload,
            )
    except httpx.HTTPError as e:
        raise LLMError(f"LLM-эндпоинт недоступен: {e}") from e
    if resp.status_code >= 400:
        raise _llm_error(resp.status_code, resp.text)
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
    timeout: httpx.Timeout | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """GET {base_url}/models — список моделей с контекстом и ценами (у OpenRouter)."""
    try:
        async with httpx.AsyncClient(timeout=timeout or LLM_TIMEOUT, transport=transport) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models", headers=_headers(base_url, api_key)
            )
    except httpx.HTTPError as e:
        raise LLMError(f"LLM-эндпоинт недоступен: {e}") from e
    if resp.status_code >= 400:
        raise _llm_error(resp.status_code, resp.text)
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
