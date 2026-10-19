"""Импорт всех таблиц для Base.metadata (doc 03)."""

from polylog.models.base import Base
from polylog.models.calls import (
    Call,
    CallMetrics,
    CallSegment,
    Objection,
    PIIFinding,
    RiskAssessment,
    Score,
    Signal,
    Violation,
)
from polylog.models.graph import (
    AgentVoice,
    Company,
    Contact,
    Deal,
    EntityLink,
    Interaction,
    PhoneNumber,
    TextMention,
)
from polylog.models.system import (
    AuditLog,
    Connector,
    DatasetManifest,
    ExportJob,
    Insight,
    Label,
    LexiconEntry,
    ModelRegistry,
    Org,
    Rubric,
    User,
)

__all__ = [
    "Base",
    "AgentVoice",
    "AuditLog",
    "Call",
    "CallMetrics",
    "CallSegment",
    "Company",
    "Connector",
    "Contact",
    "DatasetManifest",
    "Deal",
    "EmbeddingPlaceholder",
    "EntityLink",
    "ExportJob",
    "Insight",
    "Interaction",
    "Label",
    "LexiconEntry",
    "ModelRegistry",
    "Objection",
    "Org",
    "PIIFinding",
    "PhoneNumber",
    "RiskAssessment",
    "Rubric",
    "Score",
    "Signal",
    "TextMention",
    "User",
    "Violation",
]


class EmbeddingPlaceholder:
    """TODO M1: таблица embeddings на pgvector (halfvec(768), HNSW) — doc 03 §5.
    На sqlite-этапе векторы не хранятся; API контракта не меняется."""
