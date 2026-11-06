"""Pydantic DTO по доменам (ТЗ §3.1). Реэкспорт для обратной совместимости:
`from polylog.api.schemas import CallOut` работает как раньше."""

from polylog.api.schemas.auth import LoginRequest, TokenResponse, UserCreate, UserOut, UserUpdate  # noqa: F401
from polylog.api.schemas.calls import (  # noqa: F401
    CallDetail,
    CallList,
    CallOut,
    ObjectionOut,
    ScoreOut,
    SegmentOut,
    UploadResult,
)
from polylog.api.schemas.connectors import ConnectorCreate, ConnectorOut, ConnectorUpdate  # noqa: F401
from polylog.api.schemas.llm import AIAnalyzeRequest, AIContextRequest, PiiStatsOut  # noqa: F401
from polylog.api.schemas.settings import LexiconEntryCreate, RubricUpdate  # noqa: F401
