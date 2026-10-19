"""Сборка call_artifact (слой A, doc 05 §1) из БД + валидация по JSON-схеме.

ПДн: экспорт по умолчанию проходит mask-политику (doc 04 §3, doc 05 §1 правила слоя A).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from polylog import __version__
from polylog.pii.detect import detect_pii, mask_text

SCHEMA_VERSION = "1.0.0"
SPEC_NAME = "call-artifact/1.0"


def build_call_artifact(
    *,
    call: Any,
    segments: list[Any],
    metrics: dict[str, Any] | None,
    objections: list[Any],
    signals: list[Any],
    scores: list[dict[str, Any]],
    pii_policy: str = "mask",
) -> dict[str, Any]:
    """call — ORM Call; segments/objections/signals — ORM-строки; scores — dict от engine."""

    def _clean(text: str) -> str:
        if pii_policy in ("mask", "redact") and detect_pii(text):
            return mask_text(text)
        return text

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_id": f"01{uuid.uuid4().hex[:24].upper()}",
        "generator": {"product": "polylog", "version": __version__, "spec": SPEC_NAME},
        "call": {
            "call_id": str(call.id),
            "direction": call.direction,
            "started_at": call.started_at.isoformat(),
            "duration_sec": call.duration_sec or 0,
            "language": call.language or "ru",
            "participants": _participants(segments),
            "crm_refs": None,
            "previous_call_id": str(call.previous_call_id) if call.previous_call_id else None,
            "chain_depth": call.chain_depth,
        },
        "transcript": [
            {
                "idx": s.idx,
                "speaker": s.speaker,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": _clean(s.text),
                "conf": round(s.conf, 4) if s.conf is not None else None,
            }
            for s in segments
        ],
        "metrics": metrics,
        "objections": [
            {
                "id": f"obj-{o.id}",
                "type": o.type,
                "subtype": o.subtype,
                "quote": _clean(o.span_text),
                "start_ms": o.start_ms or 0,
                "end_ms": o.end_ms or (o.start_ms or 0),
                "speaker": o.speaker or "client",
                "response": {
                    "status": o.response_status or "ignored",
                    "quote": _clean(o.response_span) if o.response_span else None,
                    "start_ms": None,
                    "end_ms": o.response_end_ms,
                    "latency_ms": None,
                },
                "confidence": o.confidence,
                "model_id": o.model_id,
            }
            for o in objections
        ],
        "signals": [
            {
                "kind": s.kind,
                "quote": _clean(s.span_text),
                "start_ms": s.start_ms or 0,
                "confidence": s.confidence,
            }
            for s in signals
        ],
        "scoring": _scoring(scores, pii_policy),
        "risk": {
            "prob_loss": None,
            "abstained": True,
            "abstain_reason": "risk model not deployed (M5, doc 08)",
            "horizon_days": 14,
            "factors": [],
            "model_id": None,
        },
        "provenance": {
            "asr_backend": call.asr_backend_id or "unknown",
            "lexicon_hash": None,
            "pii_policy": pii_policy,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }
    return artifact


def _participants(segments: list[Any]) -> list[dict[str, Any]]:
    roles: list[str] = []
    for s in segments:
        if s.speaker not in roles:
            roles.append(s.speaker)
    return [{"role": r, "display_name": None, "crmid": None} for r in roles] or [
        {"role": "unknown", "display_name": None, "crmid": None}
    ]


def _scoring(scores: list[dict[str, Any]], pii_policy: str) -> dict[str, Any] | None:
    if not scores:
        return None
    latest = scores[-1]

    def _clean(text: Any) -> str:
        return mask_text(str(text)) if pii_policy in ("mask", "redact") else str(text)

    return {
        "rubric_id": latest.get("rubric_id", "default_b2b_v1"),
        "rubric_version": latest.get("rubric_version", 1),
        "total": latest["total"],
        "items": [
            {
                "item_id": it["item_id"],
                "score": it["score"],
                "weight": it["weight"],
                "explanation": _clean(it.get("explanation", "")),
                "evidence": [
                    {
                        "ref": ev.get("ref_id"),
                        "span": _clean(ev.get("span", "")),
                        "start_ms": ev.get("start_ms"),
                        "method": ev.get("method"),
                    }
                    for ev in it.get("evidence", [])
                ],
            }
            for it in latest["items"]
        ],
    }


def validate_artifact(artifact: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Валидация по call-artifacts.schema.json (draft 2020-12); список ошибок."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path)}: {err.message}"
        for err in sorted(validator.iter_errors(artifact), key=lambda e: list(e.absolute_path))
    ]
