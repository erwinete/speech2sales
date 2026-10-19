"""Правила-детекция находок v0 (obj/sig/resp/violations) поверх сегментов.

Шейп находок идентичен ML-головам M2: цитата + таймкод + confidence + model_id
(объяснимость обязательна, doc 01 §3 п.5). Классы = taxonomy.json.
"""

import re
from dataclasses import dataclass, field

from polylog.nlp import lexicons as L

RULES_MODEL_ID = "rules-nlp@0.1.0"
RULES_CONF = 0.60
RESPONSE_WINDOW_MS = 30_000  # ответ агента ищем в течение 30 c после возражения


@dataclass
class Finding:
    kind: str            # objection|signal|violation
    type: str            # obj/sig/violation id (taxonomy.json)
    span_text: str
    start_ms: int
    end_ms: int
    speaker: str
    segment_idx: int
    confidence: float = RULES_CONF
    model_id: str = RULES_MODEL_ID
    response_status: str | None = None
    response_span: str | None = None
    response_end_ms: int | None = None
    extra: dict = field(default_factory=dict)


def _match_first(text: str, patterns: tuple[re.Pattern, ...]) -> re.Match | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


def detect_findings(segments: list[dict]) -> list[Finding]:
    """segments: [{idx, speaker, start_ms, end_ms, text}] в хронологическом порядке."""
    findings: list[Finding] = []

    for seg in segments:
        # моно-записи дают speaker=unknown: возражения ищем и там (recall;
        # точность ролей обеспечивают стерео-каналы/диаризация, doc 02 §2.3)
        is_client = seg["speaker"].startswith("client") or seg["speaker"] == "unknown"
        if is_client:
            for type_, patterns in L.OBJECTION_PATTERNS.items():
                if _match_first(seg["text"], patterns):
                    findings.append(
                        Finding(
                            kind="objection",
                            type=type_,
                            span_text=seg["text"],
                            start_ms=seg["start_ms"],
                            end_ms=seg["end_ms"],
                            speaker=seg["speaker"],
                            segment_idx=seg["idx"],
                        )
                    )
                    break  # одно возражение на реплику (v0)

        for type_, patterns in L.SIGNAL_PATTERNS.items():
            if _match_first(seg["text"], patterns):
                findings.append(
                    Finding(
                        kind="signal",
                        type=type_,
                        span_text=seg["text"],
                        start_ms=seg["start_ms"],
                        end_ms=seg["end_ms"],
                        speaker=seg["speaker"],
                        segment_idx=seg["idx"],
                    )
                )

        if _match_first(seg["text"], L.VIOLATION_PATTERNS):
            findings.append(
                Finding(
                    kind="violation",
                    type="crit.no_forbidden_phrases",
                    span_text=seg["text"],
                    start_ms=seg["start_ms"],
                    end_ms=seg["end_ms"],
                    speaker=seg["speaker"],
                    segment_idx=seg["idx"],
                )
            )

    _classify_objection_responses(findings, segments)
    return findings


def _classify_objection_responses(findings: list[Finding], segments: list[dict]) -> None:
    """resp.*: (возражение клиента → следующая реплика агента в окне) (doc 02 §3.2)."""
    agent_segs = [s for s in segments if s["speaker"].startswith("agent")]
    for f in findings:
        if f.kind != "objection":
            continue
        window = [
            s for s in agent_segs
            if f.end_ms <= s["start_ms"] <= f.end_ms + RESPONSE_WINDOW_MS
        ]
        if not window:
            f.response_status = "ignored"
            continue
        resp = window[0]
        f.response_span = resp["text"]
        f.response_end_ms = resp["end_ms"]
        if _match_first(resp["text"], L.DEFERRAL_PATTERNS):
            f.response_status = "deferred"
        elif _match_first(resp["text"], L.SUCCESS_PATTERNS):
            f.response_status = "handled_success"
        else:
            f.response_status = "handled_partial"


def handled_success_ratio(objections: list[Finding]) -> float:
    if not objections:
        return 0.0
    ok = sum(1 for o in objections if o.response_status == "handled_success")
    return ok / len(objections)


def agent_open_questions(segments: list[dict]) -> int:
    """Открытые вопросы агента (для критерия needs, doc 02 §4.1).
    unknown-роль (моно) считается потенциально агентской."""
    count = 0
    for seg in segments:
        if seg["speaker"].startswith("client"):
            continue
        if seg["text"].rstrip().endswith("?") and L.OPEN_QUESTION_MARKERS.search(seg["text"]):
            count += 1
    return count


def lexicon_hit(segments: list[dict], patterns: tuple[re.Pattern, ...], scope: str) -> dict | None:
    """Поиск скриптового маркера в scope (first_60s | last_60s) → цитата или None.
    unknown-роль (моно) не отсекается — маркеры ищем во всех репликах окна."""
    if not segments:
        return None
    if scope == "first_60s":
        window = [s for s in segments if s["start_ms"] <= 60_000 and not s["speaker"].startswith("client")]
    else:  # last_60s
        total_end = max(s["end_ms"] for s in segments)
        window = [
            s for s in segments
            if s["end_ms"] >= total_end - 60_000 and not s["speaker"].startswith("client")
        ]
    for seg in window:
        m = _match_first(seg["text"], patterns)
        if m:
            return {"span_text": seg["text"], "start_ms": seg["start_ms"], "segment_idx": seg["idx"]}
    return None
