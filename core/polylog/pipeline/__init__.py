"""Оркестрация пайплайна обработки звонка (doc 01 §5).

Стадии идемпотентны, state machine живёт в calls.state:
discovered → normalized → transcribed → lexicon_corrected → analyzed → scored → done.

Асинхронные ленивые загрузки связей в AsyncSession запрещены (MissingGreenlet) —
все стадии читают дочерние строки явными select'ами. Прод-версия: отдельные
procrastinate-задачи; dev — inline.
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from polylog.asr import AsrBackendError, get_backend
from polylog.config import Settings
from polylog.media.normalize import MediaError, normalize_call_audio
from polylog.models.calls import (
    Call,
    CallMetrics,
    CallSegment,
    Objection,
    PIIFinding,
    Score,
    Signal,
    Violation,
)
from polylog.models.enums import CallState, advance
from polylog.models.system import Rubric
from polylog.nlp.rules import Finding, agent_open_questions, detect_findings
from polylog.pii.detect import detect_pii
from polylog.scoring.engine import DEFAULT_RUBRIC_SPEC, SCORER_VERSION, evaluate
from polylog.storage import Storage

log = logging.getLogger("polylog.pipeline")


class PipelineError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


async def _load_call(session: AsyncSession, call_id: uuid.UUID) -> Call:
    call = await session.get(Call, call_id)
    if call is None:
        raise PipelineError("load", f"звонок {call_id} не найден")
    return call


async def _set_state(call: Call, target: CallState) -> None:
    call.state = advance(CallState(call.state), target).value


def _fail(call: Call, stage: str, error: str) -> None:
    call.state = CallState.failed.value
    call.stage_error = {
        "stage": stage,
        "error": error,
        "at": datetime.now(UTC).isoformat(),
    }


async def _load_segments(session: AsyncSession, call_id: uuid.UUID) -> list[CallSegment]:
    return list(
        (
            await session.execute(
                select(CallSegment).where(CallSegment.call_id == call_id).order_by(CallSegment.idx)
            )
        )
        .scalars()
        .all()
    )


def _segment_dicts(segments: list[CallSegment]) -> list[dict]:
    return [
        {"idx": s.idx, "speaker": s.speaker, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
        for s in segments
    ]


async def stage_normalize(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """discovered → normalized: нормализация аудио + карта каналов + длительность."""
    if not call.recording_key or not storage.exists(call.recording_key):
        raise PipelineError("normalize", f"запись отсутствует в хранилище: {call.recording_key!r}")
    source = storage.path(call.recording_key)
    target_key = f"{call.recording_key}.16k.wav"
    try:
        norm = normalize_call_audio(source, storage.path(target_key))
    except MediaError as e:
        raise PipelineError("normalize", str(e)) from e
    call.normalized_key = call.recording_key if norm.reused else target_key
    if call.normalized_key != call.recording_key:
        # sidecar-эталон едет вместе с нормализованной копией (stub-ASR ищет рядом)
        sidecar_src, sidecar_dst = f"{call.recording_key}.transcript.json", f"{target_key}.transcript.json"
        if storage.exists(sidecar_src) and not storage.exists(sidecar_dst):
            storage.save(sidecar_dst, storage.open(sidecar_src))
    call.duration_sec = int(round(norm.duration_sec))
    call.channels_map = norm.channels_map
    await _set_state(call, CallState.normalized)


async def stage_transcribe(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """normalized → transcribed: VAD/роли/ASR через выбранный бэкенд (doc 02 §2.4)."""
    if not call.normalized_key:
        raise PipelineError("transcribe", "normalized_key не установлен")
    try:
        backend = get_backend(settings.asr_backend)
    except AsrBackendError as e:
        raise PipelineError("transcribe", str(e)) from e
    if not storage.exists(call.normalized_key):
        raise PipelineError("transcribe", f"нормализованное аудио отсутствует: {call.normalized_key!r}")
    wav_path = storage.path(call.normalized_key)

    # Runtime-валидация карты каналов — авто-flip стерео (doc 02 §2.3 п.1, DoD М3 §1)
    prepare = getattr(backend, "prepare_channels", None)
    if prepare is not None and call.channels_map:
        try:
            new_map, status = prepare(wav_path, call.channels_map)
            if new_map is not None and new_map != call.channels_map:
                call.channels_map = new_map
        except Exception as e:  # noqa: BLE001 — валидация не должна ронять транскрибацию
            log.warning("prepare_channels %s: %s", call.id, e)

    # Voiceprint-подсказка для mono (DoD М3 §2.1): отпечатки агентов из БД
    hints: dict | None = None
    if call.channels_map is None:
        from polylog.asr import diarize as diarize_mod
        from polylog.asr import voiceprint as voiceprint_mod

        if diarize_mod.available() and voiceprint_mod.available():
            try:
                voices = await voiceprint_mod.get_agent_voices(session, call.org_id)
                if voices:
                    hints = {"agent_voices": voices}
            except Exception as e:  # noqa: BLE001
                log.warning("voiceprint-подсказка: %s", e)

    try:
        utterances = backend.transcribe(wav_path, call.channels_map, hints)
    except AsrBackendError as e:
        raise PipelineError("transcribe", str(e)) from e

    # идемпотентность (doc 01 §5.1): репроцессинг не дублирует сегменты
    await session.execute(delete(CallSegment).where(CallSegment.call_id == call.id))

    for idx, u in enumerate(utterances):
        session.add(
            CallSegment(
                call_id=call.id,
                idx=idx,
                speaker=u.speaker,
                start_ms=u.start_ms,
                end_ms=u.end_ms,
                text=u.text,
                raw_text=u.raw_text,
                conf=u.conf,
                words=[{"w": w.text, "s": w.start_ms, "e": w.end_ms, "c": w.conf} for w in u.words]
                or None,
            )
        )
    confs = [u.conf for u in utterances if u.conf is not None]
    call.asr_backend_id = backend.id
    call.avg_conf = round(sum(confs) / len(confs), 4) if confs else None
    await session.flush()
    await _set_state(call, CallState.transcribed)


async def stage_postprocess(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """transcribed → lexicon_corrected: пост-ASR обработка — PII-детекция + регистр
    находок (doc 04 §3). Lexicon-коррекция L1 (rapidfuzz) — M2; стадия уже в контракте."""
    await session.execute(delete(PIIFinding).where(PIIFinding.call_id == call.id))
    for seg in await _load_segments(session, call.id):
        for span in detect_pii(seg.text):
            session.add(
                PIIFinding(
                    call_id=call.id,
                    kind=span.kind,
                    action=settings.pii_action,
                    segment_idx=seg.idx,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    detector=span.detector,
                )
            )
    await _set_state(call, CallState.lexicon_corrected)


def compute_metrics(utterances: list[dict]) -> dict:
    """Метрики разговора без ML (doc 02 §3.3): talk_ratio, паузы, вопросы по ролям."""
    speech_by_role: dict[str, int] = {}
    speech_total = 0
    gaps: list[int] = []
    prev_end: int | None = None
    questions = {"agent": 0, "client": 0, "total": 0}
    for u in utterances:
        dur = max(0, u["end_ms"] - u["start_ms"])
        speech_by_role[u["speaker"]] = speech_by_role.get(u["speaker"], 0) + dur
        speech_total += dur
        if prev_end is not None and u["start_ms"] > prev_end:
            gaps.append(u["start_ms"] - prev_end)
        prev_end = max(prev_end or 0, u["end_ms"])
        if u["text"].rstrip().endswith("?"):
            questions["total"] += 1
            questions["agent" if u["speaker"].startswith("agent") else "client"] += 1
    pauses = [g for g in gaps if g >= 2000]  # порог паузы 2 c
    from polylog.nlp.sentiment import client_sentiment

    return {
        "talk_ratio": {
            role: round(d / speech_total, 4) if speech_total else 0.0
            for role, d in speech_by_role.items()
        },
        "pauses": {
            "count": len(pauses),
            "total_sec": round(sum(pauses) / 1000, 2),
            "longest_sec": round(max(pauses) / 1000, 2) if pauses else 0.0,
        },
        "questions": questions,
        "client_sentiment": client_sentiment(utterances),
    }


async def stage_analyze(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """lexicon_corrected → analyzed: метрики из таймингов + находки правил v0
    (возражения/сигналы/нарушения; ML-головы — M2, doc 02 §3) + NLI «вопрос → ответ»
    (ADR-14, если настроен nli_model_dir)."""
    segments = await _load_segments(session, call.id)
    seg_dicts = _segment_dicts(segments)

    await session.execute(delete(CallMetrics).where(CallMetrics.call_id == call.id))
    metrics = compute_metrics(seg_dicts) if seg_dicts else {}

    await session.execute(delete(Objection).where(Objection.call_id == call.id))
    await session.execute(delete(Signal).where(Signal.call_id == call.id))
    await session.execute(delete(Violation).where(Violation.call_id == call.id))

    if seg_dicts:
        for f in detect_findings(seg_dicts):
            if f.kind == "objection":
                session.add(
                    Objection(
                        call_id=call.id, type=f.type, span_text=f.span_text,
                        start_ms=f.start_ms, end_ms=f.end_ms, speaker=f.speaker,
                        response_status=f.response_status, response_span=f.response_span,
                        response_end_ms=f.response_end_ms,
                        confidence=f.confidence, model_id=f.model_id,
                    )
                )
            elif f.kind == "signal":
                session.add(
                    Signal(call_id=call.id, kind=f.type, span_text=f.span_text,
                           start_ms=f.start_ms, confidence=f.confidence, model_id=f.model_id)
                )
            else:
                session.add(
                    Violation(call_id=call.id, kind=f.type, span_text=f.span_text,
                              start_ms=f.start_ms, model_id=f.model_id)
                )

    nli = await _nli_check(session, call, seg_dicts, settings)
    if nli:
        metrics["nli_answered_ratio"] = nli["answered"] / nli["pairs"]
        metrics["nli"] = nli

    if seg_dicts:
        session.add(CallMetrics(call_id=call.id, metrics=metrics))

    call.analyzed_at = datetime.now(UTC)
    await _set_state(call, CallState.analyzed)


async def _nli_check(
    session: AsyncSession, call: Call, seg_dicts: list[dict], settings: Settings
) -> dict | None:
    """NLI-проверка «вопрос клиента → ответ агента» (ADR-14). None — выключено/нет пар."""
    if not settings.nli_model_dir:
        return None
    if not Path(settings.nli_model_dir, "multitask_model.pt").is_file():
        log.warning("NLI-чекпойнт не найден: %s — стадия пропущена", settings.nli_model_dir)
        return None
    from polylog.scoring.nli_backend import NliScorer, match_qa_pairs

    pairs = [p for p in match_qa_pairs(seg_dicts) if p["answer"]]
    if not pairs:
        return None
    scorer = NliScorer(settings.nli_model_dir)
    verdicts = scorer.score_batch([(p["question"], p["answer"]) for p in pairs])
    answered = 0
    for p, v in zip(pairs, verdicts, strict=True):
        if v.answered:
            answered += 1
        else:
            session.add(
                Violation(
                    call_id=call.id,
                    kind="crit.question_ignored",
                    span_text=f"В: {p['question'][:120]} || О: {p['answer'][:120]}",
                    start_ms=p["question_start_ms"],
                    model_id=f"nli-rubert-v2:{v.label}",
                )
            )
    return {"pairs": len(pairs), "answered": answered, "ignored": len(pairs) - answered}


async def stage_score(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """analyzed → scored: rubric-engine с evidence (doc 02 §4). Рубрика создаётся
    при первом звонке организации (default_b2b_v1); замена — через rubrics в UI (M2)."""
    rubric = (
        await session.execute(
            select(Rubric).where(Rubric.org_id == call.org_id, Rubric.name == DEFAULT_RUBRIC_SPEC["rubric_id"])
        )
    ).scalar_one_or_none()
    if rubric is None:
        rubric = Rubric(
            org_id=call.org_id, name=DEFAULT_RUBRIC_SPEC["rubric_id"],
            version=DEFAULT_RUBRIC_SPEC["version"], spec=DEFAULT_RUBRIC_SPEC,
        )
        session.add(rubric)
        await session.flush()
    elif rubric.spec != DEFAULT_RUBRIC_SPEC:
        # спека рубрики обновилась в коде — перетираем с бампом версии (dev-режим;
        # прод: versioned rubrics + рескоринг фоном, doc 02 §4)
        rubric.spec = DEFAULT_RUBRIC_SPEC
        rubric.version = DEFAULT_RUBRIC_SPEC["version"]

    segments = await _load_segments(session, call.id)
    seg_dicts = _segment_dicts(segments)
    metrics_row = (
        await session.execute(select(CallMetrics).where(CallMetrics.call_id == call.id))
    ).scalar_one_or_none()
    metrics = metrics_row.metrics if metrics_row else {"agent_questions": agent_open_questions(seg_dicts)}

    objections = list(
        (await session.execute(select(Objection).where(Objection.call_id == call.id))).scalars().all()
    )
    signals = list(
        (await session.execute(select(Signal).where(Signal.call_id == call.id))).scalars().all()
    )
    violations = list(
        (await session.execute(select(Violation).where(Violation.call_id == call.id))).scalars().all()
    )

    findings: list[Finding] = [
        Finding(kind="objection", type=o.type, span_text=o.span_text, start_ms=o.start_ms or 0,
                end_ms=o.end_ms or 0, speaker=o.speaker or "client", segment_idx=0,
                confidence=o.confidence, model_id=o.model_id, response_status=o.response_status,
                response_span=o.response_span, response_end_ms=o.response_end_ms)
        for o in objections
    ]
    findings += [
        Finding(kind="signal", type=s.kind, span_text=s.span_text, start_ms=s.start_ms or 0,
                end_ms=s.start_ms or 0, speaker="unknown", segment_idx=0,
                confidence=s.confidence, model_id=s.model_id)
        for s in signals
    ]
    findings += [
        Finding(kind="violation", type=v.kind, span_text=v.span_text, start_ms=v.start_ms or 0,
                end_ms=v.start_ms or 0, speaker="unknown", segment_idx=0,
                confidence=1.0, model_id=v.model_id)
        for v in violations
    ]

    result = evaluate(rubric.spec, segments=seg_dicts, metrics=metrics, findings=findings)
    await session.execute(delete(Score).where(Score.call_id == call.id))
    session.add(
        Score(
            call_id=call.id,
            rubric_id=rubric.id,
            rubric_version=rubric.version,
            total=result["total"],
            items=[
                {
                    "item_id": it["item_id"],
                    "title": it.get("title"),
                    "score": it["score"],
                    "weight": it["weight"],
                    "explanation": it["explanation"],
                    "evidence": it["evidence"],
                }
                for it in result["items"]
            ],
            scorer_version=SCORER_VERSION,
        )
    )
    await _set_state(call, CallState.scored)


async def stage_embed(session: AsyncSession, call: Call, storage: Storage, settings: Settings) -> None:
    """scored → embedded: вектор звонка → pgvector (doc 02 §5, M9). На sqlite — no-op."""
    await _enroll_agent_voice_if_needed(session, call, storage)
    if not engine_is_postgres(session):
        await _set_state(call, CallState.embedded)
        return
    segments = await _load_segments(session, call.id)
    if not segments:
        await _set_state(call, CallState.embedded)
        return
    if call.duration_sec is not None and call.duration_sec < 15:
        # short_call (<15 c) — вне семантического анализа (DoD М1): недозвон
        # не должен попадать в похожие звонки и кластеры возражений
        log.info("embed пропущен: звонок %s короче 15 c", call.id)
        await _set_state(call, CallState.embedded)
        return
    from polylog.embeddings import embed_call_text

    try:
        vector, model_id = embed_call_text(_segment_dicts(segments))
    except Exception as e:  # noqa: BLE001 — модель недоступна: стадия skip, не fail
        log.warning("embed пропущен для %s: %s", call.id, e)
        await _set_state(call, CallState.embedded)
        return

    vec_literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    await session.execute(
        text(
            "INSERT INTO embeddings (org_id, entity_type, entity_id, model_id, dim, vector, meta) "
            "VALUES (:org, 'call', :eid, :mid, :dim, CAST(:vec AS halfvec), CAST(:meta AS jsonb)) "
            "ON CONFLICT (entity_type, entity_id, model_id) "
            "DO UPDATE SET vector = EXCLUDED.vector"
        ),
        {"org": call.org_id, "eid": str(call.id), "mid": model_id, "dim": len(vector),
         "vec": vec_literal, "meta": '{"kind":"call_mean"}'},
    )
    await _set_state(call, CallState.embedded)


def engine_is_postgres(session: AsyncSession) -> bool:
    return session.bind is not None and session.bind.url.get_backend_name().startswith("postgresql")


def _agent_extension(call: Call) -> str | None:
    """Внутренний номер агента (ключ voiceprint): у исходящего — phone_from,
    у входящего — phone_to; короткий числовой без «+» (не E.164-клиент)."""
    candidate = call.phone_from if call.direction == "outbound" else call.phone_to
    if (
        candidate
        and not candidate.startswith("+")
        and candidate.isdigit()
        and len(candidate) <= 6
    ):
        return candidate
    return None


async def _enroll_agent_voice_if_needed(session: AsyncSession, call: Call, storage: Storage) -> None:
    """Voiceprint enrollment (DoD М3 §2.1): стерео-звонок с разрешённым
    агентским каналом пополняет голосовой отпечаток агента. Ошибки не должны
    ронять пайплайн; выключено без POLYLOG_VOICEPRINT=1 + HF_TOKEN."""
    try:
        from polylog.asr import voiceprint

        if (
            not voiceprint.available()
            or not call.normalized_key
            or not call.channels_map
            or not storage.exists(call.normalized_key)
        ):
            return
        agent_ch = next(
            (k for k, v in call.channels_map.items() if k in ("0", "1") and v == "agent"),
            None,
        )
        if agent_ch is None:
            return
        agent_ext = _agent_extension(call)
        if agent_ext is None:
            return
        wav_path = storage.path(call.normalized_key)
        vector = voiceprint.channel_embedding(wav_path, int(agent_ch))
        await voiceprint.enroll_agent_voice(
            session, call.org_id, agent_ext, vector, voiceprint.EMBED_MODEL
        )
        log.info("voiceprint: отпечаток агента %s пополнен (звонок %s)", agent_ext, call.id)
    except Exception as e:  # noqa: BLE001 — enrollment не роняет пайплайн
        log.warning("voiceprint enrollment %s: %s", call.id, e)


async def process_call(
    session: AsyncSession, call_id: uuid.UUID, settings: Settings, storage: Storage
) -> Call:
    """Полный прогон стадий (dev: inline). Повторный вызов на done — no-op."""
    call = await _load_call(session, call_id)
    if CallState(call.state) is CallState.failed:
        call.state = CallState.discovered.value  # перезапуск из UI
        call.stage_error = None

    stages = [
        (CallState.discovered, stage_normalize),
        (CallState.normalized, stage_transcribe),
        (CallState.transcribed, stage_postprocess),
        (CallState.lexicon_corrected, stage_analyze),
        (CallState.analyzed, stage_score),
        (CallState.scored, stage_embed),
    ]
    done_states = {CallState.embedded.value, CallState.done.value}
    for expected_state, stage in stages:
        if call.state in done_states:
            break  # идемпотентность: поздние состояния не перебегают назад
        if CallState(call.state) is not expected_state:
            continue
        try:
            await stage(session, call, storage, settings)
        except PipelineError as e:
            _fail(call, e.stage, str(e))
            raise
    call.state = CallState.done.value
    return call
