"""Роутер звонков: upload, список с фильтрами, детали, артефакт, роли, репроцесс, аудио."""

import logging
import secrets as secrets_module
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select

from polylog.api.deps import AuthDep, SessionDep, SettingsDep
from polylog.api.schemas import CallDetail, CallList, CallOut, UploadResult
from polylog.graph.service import get_default_org
from polylog.ingest.base import CallRef
from polylog.ingest.service import create_call_from_ref
from polylog.models.calls import Call, Score
from polylog.models.enums import Direction
from polylog.models.system import AuditLog, Label
from polylog.pipeline import process_call
from polylog.storage import StorageError, sha256_hex

log = logging.getLogger("polylog.api.calls")

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])


def _call_to_out(call: Call) -> CallOut:
    return CallOut(
        id=call.id,
        external_id=call.external_id,
        direction=call.direction,
        phone_from=call.phone_from,
        phone_to=call.phone_to,
        contact_id=call.contact_id,
        company_id=call.company_id,
        started_at=call.started_at,
        duration_sec=call.duration_sec,
        state=call.state,
        source=call.source,
        consent_flag=call.consent_flag,
        avg_conf=call.avg_conf,
        asr_backend_id=call.asr_backend_id,
        thread_id=call.thread_id,
        chain_depth=call.chain_depth,
        previous_call_id=call.previous_call_id,
    )


def _storage(request: Request):
    return request.app.state.storage


def _looks_stereo(audio: bytes) -> bool:
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return False
    try:
        channels = int.from_bytes(audio[22:24], "little")
    except Exception:  # noqa: BLE001
        return False
    return channels == 2


@router.post("/upload", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_call(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    user: AuthDep,
    file: Annotated[UploadFile, File()],
    direction: Annotated[str, Form()] = "outbound",
    phone_from: Annotated[str | None, Form()] = None,
    phone_to: Annotated[str | None, Form()] = None,
    started_at: Annotated[datetime | None, Form()] = None,
) -> UploadResult:
    """Generic HTTP-коннектор: загрузка записи напрямую (идемпотентно по sha256)."""
    if direction not in Direction._value2member_map_:
        raise HTTPException(422, f"direction должен быть одним из {list(Direction._value2member_map_)}")
    if not phone_from and not phone_to:
        raise HTTPException(422, "нужен хотя бы один номер: phone_from или phone_to")

    size_limit = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1 << 20):
        total += len(chunk)
        if total > size_limit:
            raise HTTPException(413, f"файл больше {settings.max_upload_mb} МБ")
        chunks.append(chunk)
    audio = b"".join(chunks)
    if not audio:
        raise HTTPException(422, "пустой файл")
    digest = sha256_hex(audio)
    external_id = f"upload-{digest[:24]}"
    suffix = Path(file.filename or "call.wav").suffix or ".wav"
    recording_key = f"calls/{{org}}/{digest[:16]}{suffix}"

    org = await get_default_org(session)
    recording_key = recording_key.format(org=org.id)
    storage = _storage(request)
    if settings.storage_dir and storage.exists(recording_key):
        pass  # ключ по контенту — идемпотентно перезаписываем тем же
    storage.save(recording_key, audio)

    ref = CallRef(
        external_id=external_id,
        started_at=started_at or datetime.now(UTC),
        direction=direction,
        phone_from=phone_from,
        phone_to=phone_to,
        recording_uri=recording_key,
        channels_hint={"0": "agent", "1": "client"} if _looks_stereo(audio) else None,
        consent_flag=True,
    )
    call = await create_call_from_ref(
        session, org, None, ref, storage, audio=audio, source="upload"
    )
    created = call is not None
    if not created:
        call = (
            (
                await session.execute(
                    select(Call).where(
                        Call.org_id == org.id,
                        Call.external_id == external_id,
                        Call.connector_id.is_(None),
                    )
                )
            )
            .scalar_one()
        )
    elif settings.inline_process:
        try:
            call = await process_call(session, call.id, settings, storage)
        except Exception as e:  # noqa: BLE001 — стадия уже пометила failed
            log.warning("пайплайн упал на звонке %s: %s", call.id, e)
    else:
        from polylog.queue import enqueue_process_call

        if not enqueue_process_call(call.id):
            log.info("звонок %s ожидает воркера (очередь недоступна)", call.id)
    await session.commit()
    await session.refresh(call)
    return UploadResult(
        call=_call_to_out(call), created=created,
        message="ok" if created else "дубликат по содержимому — существующий звонок",
    )


@router.get("", response_model=CallList)
async def list_calls(
    session: SessionDep,
    user: AuthDep,
    state: Annotated[str | None, Query()] = None,
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
    date_from: Annotated[str | None, Query()] = None,
    date_to: Annotated[str | None, Query()] = None,
    duration_min: Annotated[int | None, Query(ge=0)] = None,
    duration_max: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CallList:
    org = await get_default_org(session)
    conds = [Call.org_id == org.id]
    if state:
        conds.append(Call.state == state)
    if date_from:
        conds.append(Call.started_at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
    if date_to:
        conds.append(Call.started_at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))
    if not date_from and not date_to and days:
        conds.append(Call.started_at >= datetime.now(UTC) - timedelta(days=days))
    if duration_min is not None:
        conds.append(Call.duration_sec >= duration_min)
    if duration_max is not None:
        conds.append(Call.duration_sec <= duration_max)
    total = (
        await session.execute(select(func.count()).select_from(Call).where(*conds))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(Call).where(*conds).order_by(Call.started_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return CallList(total=total, items=[_call_to_out(c) for c in rows])


@router.get("/{call_id}", response_model=CallDetail)
async def call_detail(call_id: uuid.UUID, session: SessionDep, user: AuthDep) -> CallDetail:
    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "звонок не найден")
    base = _call_to_out(call)
    scores = (
        (
            await session.execute(
                select(Score).where(Score.call_id == call.id).order_by(Score.created_at)
            )
        )
        .scalars()
        .all()
    )
    # BUG-10: signals/violations/pii_findings/agent_name/contact_name в ответе
    from polylog.models.calls import PIIFinding
    from polylog.models.graph import Contact
    from polylog.models.system import User

    pii_findings = (
        (
            await session.execute(
                select(PIIFinding).where(PIIFinding.call_id == call.id).order_by(PIIFinding.created_at)
            )
        )
        .scalars()
        .all()
    )
    agent_name: str | None = None
    if call.agent_user_id:
        agent = await session.get(User, call.agent_user_id)
        if agent:
            agent_name = agent.display_name or agent.email
    contact_name: str | None = None
    if call.contact_id:
        contact = await session.get(Contact, call.contact_id)
        if contact:
            contact_name = contact.display_name
    return CallDetail(
        **base.model_dump(),
        stage_error=call.stage_error,
        channels_map=call.channels_map,
        recording_key=call.recording_key,
        normalized_key=call.normalized_key,
        segments=[
            {
                "idx": s.idx,
                "speaker": s.speaker,
                "start_ms": s.start_ms,
                "end_ms": s.end_ms,
                "text": s.text,
                "conf": s.conf,
            }
            for s in call.segments
        ],
        metrics=call.metrics.metrics if call.metrics else None,
        agent_name=agent_name,
        contact_name=contact_name,
        signals=[
            {
                "kind": sg.kind,
                "span_text": sg.span_text,
                "start_ms": sg.start_ms,
                "confidence": sg.confidence,
                "model_id": sg.model_id,
            }
            for sg in call.signals
        ],
        violations=[
            {
                "kind": v.kind,
                "span_text": v.span_text,
                "start_ms": v.start_ms,
                "model_id": v.model_id,
            }
            for v in call.violations
        ],
        pii_findings=[
            {
                "kind": pf.kind,
                "action": pf.action,
                "segment_idx": pf.segment_idx,
                "start_ms": pf.start_ms,
                "end_ms": pf.end_ms,
                "detector": pf.detector,
            }
            for pf in pii_findings
        ],
        objections=[
            {
                "type": o.type,
                "span_text": o.span_text,
                "start_ms": o.start_ms,
                "end_ms": o.end_ms,
                "response_status": o.response_status,
                "confidence": o.confidence,
                "model_id": o.model_id,
            }
            for o in call.objections
        ],
        scores=[
            {
                "rubric_id": str(sc.rubric_id),
                "rubric_version": sc.rubric_version,
                "total": sc.total,
                "items": sc.items,
                "scorer_version": sc.scorer_version,
            }
            for sc in scores
        ],
    )


@router.get("/{call_id}/artifact")
async def call_artifact(call_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: AuthDep) -> JSONResponse:
    """Экспорт слоя A обменного формата (doc 05 §1); валиден по схеме v1.0."""
    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "звонок не найден")
    scores = (
        (
            await session.execute(
                select(Score).where(Score.call_id == call.id).order_by(Score.created_at)
            )
        )
        .scalars()
        .all()
    )
    scores_dicts = [
        {"rubric_id": sc.rubric_id, "rubric_version": sc.rubric_version, "total": sc.total, "items": sc.items}
        for sc in scores
    ]
    metrics = call.metrics.metrics if call.metrics else None
    from polylog.export.artifact import build_call_artifact

    artifact = build_call_artifact(
        call=call,
        segments=call.segments,
        metrics=metrics,
        objections=call.objections,
        signals=call.signals,
        scores=scores_dicts,
        pii_policy=settings.pii_export_action,
    )
    return JSONResponse(artifact)


@router.post("/{call_id}/segments/{idx}/role")
async def set_segment_role(
    call_id: uuid.UUID,
    idx: int,
    session: SessionDep,
    user: AuthDep,
    speaker: Annotated[str, Form()],
) -> JSONResponse:
    """Ручная правка роли реплики: labels (target_type=segment) + сегмент."""
    if speaker not in ("agent", "client"):
        raise HTTPException(422, "speaker: agent | client")
    from polylog.models.calls import CallSegment

    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "звонок не найден")
    seg = (
        (
            await session.execute(
                select(CallSegment).where(CallSegment.call_id == call_id, CallSegment.idx == idx)
            )
        )
        .scalars()
        .first()
    )
    if seg is None:
        raise HTTPException(404, f"реплика idx={idx} не найдена")
    before = {"speaker": seg.speaker}
    seg.speaker = speaker
    session.add(
        Label(
            org_id=call.org_id,
            call_id=call.id,
            target_type="segment",
            target_id=str(idx),
            before=before,
            after={"speaker": speaker},
            author_id=user.user_id,
        )
    )
    await session.commit()
    return {"call_id": str(call_id), "idx": idx, "speaker": speaker}


@router.post("/{call_id}/reprocess", response_model=CallOut)
async def reprocess_call(
    call_id: uuid.UUID, session: SessionDep, settings: SettingsDep, user: AuthDep, request: Request
) -> CallOut:
    """Перезапуск пайплайна (failed/done → discovered → done; BUG-03: force
    для готовых звонков — раньше кнопка репроцессинга не делала ничего)."""
    call = await session.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "звонок не найден")
    try:
        call = await process_call(session, call_id, settings, _storage(request), force=True)
    except Exception as e:  # noqa: BLE001
        log.warning("репроцессинг %s упал: %s", call_id, e)
    await session.commit()
    await session.refresh(call)
    return _call_to_out(call)


@router.get("/{call_id}/audio")
async def call_audio(
    call_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    request: Request,
    api_key: Annotated[str | None, Query()] = None,
):
    """Запись звонка для плеера. Токен — через ?api_key= (плеер не умеет заголовки)."""
    if not api_key or not secrets_module.compare_digest(api_key, settings.api_token):
        raise HTTPException(401, "неверный api_key")
    call = await session.get(Call, call_id)
    if call is None or not call.recording_key:
        raise HTTPException(404, "звонок или запись не найдена")
    try:
        path = request.app.state.storage.path(call.recording_key)
    except StorageError:
        raise HTTPException(404, "запись не найдена в хранилище") from None
    session.add(AuditLog(action="audio_play", resource_type="call", resource_id=str(call.id)))
    await session.commit()
    return FileResponse(path, media_type="audio/wav", filename=path.name)
