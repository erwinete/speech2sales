"""Перечисления домена. Канонические значения совпадают с обменным форматом
(schemas/*.schema.json) и будущей таксономией ADR-15 (schemas/taxonomy.json)."""

from enum import Enum


class CallState(str, Enum):
    """State machine пайплайна (doc 01 §5.1)."""

    discovered = "discovered"
    downloading = "downloading"
    downloaded = "downloaded"
    normalized = "normalized"
    diarized = "diarized"
    transcribed = "transcribed"
    lexicon_corrected = "lexicon_corrected"
    analyzed = "analyzed"
    scored = "scored"
    embedded = "embedded"
    risk_assessed = "risk_assessed"
    done = "done"
    failed = "failed"


CALL_STATE_ORDER: list[CallState] = [
    CallState.discovered,
    CallState.downloading,
    CallState.downloaded,
    CallState.normalized,
    CallState.diarized,
    CallState.transcribed,
    CallState.lexicon_corrected,
    CallState.analyzed,
    CallState.scored,
    CallState.embedded,
    CallState.risk_assessed,
    CallState.done,
]


def advance(current: CallState, target: CallState) -> CallState:
    """Возвращает состояние, наиболее продвинутое из двух (стадии идемпотентны
    и могут пропускаться: scoring/embedding — no-op в skeleton)."""
    if current is CallState.failed or target is CallState.failed:
        return CallState.failed
    order = {s: i for i, s in enumerate(CALL_STATE_ORDER)}
    return target if order[target] >= order[current] else current


class Direction(str, Enum):
    inbound = "inbound"
    outbound = "outbound"
    internal = "internal"


class SpeakerRole(str, Enum):
    agent = "agent"
    client = "client"
    agent_2 = "agent_2"
    client_2 = "client_2"
    unknown = "unknown"


# Такономия возражений v1 (doc 02 §3.2; = enum objection.type в call-artifacts.schema.json)
OBJECTION_TYPES = (
    "price",
    "existing_supplier",
    "send_offer",
    "timing",
    "no_authority",
    "trust",
    "not_interested",
    "legal_contract",
    "competitor_compare",
    "other",
)

RESPONSE_STATUSES = (
    "handled_success",
    "handled_partial",
    "ignored",
    "deferred",
    "failed",
)

SIGNAL_KINDS = (
    "next_step_agreed",
    "budget_mentioned",
    "timeline_mentioned",
    "authority_confirmed",
    "details_requested",
    "demo_positive",
)

DIALOG_STAGES = (
    "greeting",
    "identification",
    "qualification",
    "presentation",
    "objection_handling",
    "negotiation",
    "closing",
    "goodbye",
)

LINK_SOURCES = ("crm", "phone_match", "ner_match", "manual")
