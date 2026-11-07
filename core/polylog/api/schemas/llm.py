"""Pydantic-схемы AI Lab (ТЗ v3.0 §4.4): выборка контекста, слайдер ПДн,
запуск LLM-анализа."""

from pydantic import BaseModel, Field

from polylog.llm.prompts import DEFAULT_SYSTEM_PROMPT
from polylog.pii.sanitizer import PiiSanitizerConfig


class AIContextRequest(BaseModel):
    """Параметры выборки данных + состояние слайдера очистки ПДн."""

    mode: str = "rubert_scores"  # rubert_scores | problematic_calls | transcripts_range
    date_from: str | None = None
    date_to: str | None = None
    days: int = 30
    agent_user_id: str | None = None
    agent_name: str | None = None
    risk_band: str | None = None  # high | medium (medium = средний и выше)
    score_max: float | None = None
    direction: str | None = None
    min_duration_sec: int | None = None
    objection_type: str | None = None
    call_ids: list[str] = Field(default_factory=list)
    limit_calls: int = 30
    # DEF-03 (ТЗ v4.0 §8.1): бюджет контекстного окна и умное сжатие транскриптов
    max_context_tokens: int = 48000
    smart_compress: bool = True
    pii: PiiSanitizerConfig = Field(default_factory=PiiSanitizerConfig)


class AIAnalyzeRequest(AIContextRequest):
    """AIContextRequest + настройки LLM-эндпоинта."""

    provider: str = "openrouter"  # openrouter | openai_custom
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str | None = None
    model: str = "anthropic/claude-3.7-sonnet"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    user_prompt: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096


class PiiStatsOut(BaseModel):
    total_redactions: int = 0
    by_category: dict[str, int] = Field(default_factory=dict)
    alias_map: dict[str, str] = Field(default_factory=dict)
