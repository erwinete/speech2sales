"""LLM-модуль «Полилога» (ТЗ v3.0 §3.1): клиент OpenAI-compatible API,
сборщик контекста и промпты. Внешние вызовы — только по явному запросу
пользователя из AI Lab; базовый пайплайн остаётся 100% локальным."""

from polylog.llm.client import LLMError, chat_completion, list_models
from polylog.llm.context_builder import ContextBundle, build_context
from polylog.llm.prompts import DEFAULT_SYSTEM_PROMPT, PRESETS, RECOMMENDED_MODELS

__all__ = [
    "LLMError",
    "chat_completion",
    "list_models",
    "ContextBundle",
    "build_context",
    "DEFAULT_SYSTEM_PROMPT",
    "PRESETS",
    "RECOMMENDED_MODELS",
]
