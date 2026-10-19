"""FastAPI-приложение «Полилога» (doc 01 §4.2): REST для звонков/транскриптов,
upload-коннектор, webhook-приём телефонии/CRM, healthz. SSE — следующий шаг."""

import hashlib
import hmac as hmac_mod
import json
import logging
import os
import re
import secrets as secrets_module
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from polylog.api.deps import AuthDep, SessionDep, SettingsDep
from polylog.api.schemas import CallDetail, CallList, CallOut, UploadResult
from polylog.config import Settings
from polylog.config import get_settings as _default_settings
from polylog.db import init_db, make_engine, make_sessionmaker
from polylog.graph.service import get_default_org
from polylog.ingest.base import CallRef
from polylog.ingest.service import create_call_from_ref
from polylog.models.calls import Call
from polylog.models.enums import Direction
from polylog.models.system import Insight
from polylog.pipeline import process_call
from polylog.storage import StorageError, make_storage, sha256_hex

log = logging.getLogger("polylog.api")


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


async def _ensure_default_org(session) -> None:
    """Skeleton: одна организация по умолчанию (multi-org модель сохранена, doc 03 §2)."""
    await get_default_org(session)


def _hook_secret(connector: str) -> str | None:
    """Секрет HMAC webhook'а (doc 04 §6): env POLYLOG_HOOK_SECRET_{KIND}."""
    return os.environ.get(f"POLYLOG_HOOK_SECRET_{connector.upper()}")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or _default_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    storage = make_storage(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.tmp_dir).mkdir(parents=True, exist_ok=True)
        if settings.autocreate_tables:
            await init_db(engine)
        async with sessionmaker() as session:
            await _ensure_default_org(session)
            await session.commit()
        log.warning(
            "API-токен: %s — замените POLYLOG_API_TOKEN перед боевым запуском (doc 04)",
            "дефолтный dev-токен" if settings.api_token == "dev-insecure-token" else "из конфига",
        )
        yield

    app = FastAPI(title="Polylog Speech Analytics", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.storage = storage

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": app.version})

    @app.post("/api/v1/calls/upload", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
    async def upload_call(
        settings: SettingsDep,
        session: SessionDep,
        _: AuthDep,
        file: Annotated[UploadFile, File()],
        direction: Annotated[str, Form()] = "outbound",
        phone_from: Annotated[str | None, Form()] = None,
        phone_to: Annotated[str | None, Form()] = None,
        started_at: Annotated[datetime | None, Form()] = None,
    ) -> UploadResult:
        """Generic HTTP-коннектор (doc 02 §1.2): загрузка записи напрямую.
        Идемпотентность: external_id = sha256 контента → повторная загрузка не создаёт дубль."""
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
            # дубликат по содержимому: возвращаем существующий звонок
            call = (
                await session.execute(
                    select(Call).where(
                        Call.org_id == org.id,
                        Call.external_id == external_id,
                        Call.connector_id.is_(None),
                    )
                )
            ).scalar_one()
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

    @app.get("/api/v1/calls", response_model=CallList)
    async def list_calls(
        session: SessionDep,
        _: AuthDep,
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

    @app.get("/api/v1/calls/{call_id}", response_model=CallDetail)
    async def call_detail(call_id: uuid.UUID, session: SessionDep, _: AuthDep) -> CallDetail:
        call = await session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "звонок не найден")
        base = _call_to_out(call)
        from polylog.models.calls import Score

        scores = (
            (
                await session.execute(
                    select(Score).where(Score.call_id == call.id).order_by(Score.created_at)
                )
            )
            .scalars()
            .all()
        )
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

    @app.get("/api/v1/calls/{call_id}/artifact")
    async def call_artifact(call_id: uuid.UUID, session: SessionDep, settings: SettingsDep, _: AuthDep) -> JSONResponse:
        """Экспорт слоя A обменного формата (doc 05 §1); валиден по схеме v1.0."""
        from polylog.models.calls import Score

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

    @app.post("/api/v1/calls/{call_id}/segments/{idx}/role")
    async def set_segment_role(
        call_id: uuid.UUID,
        idx: int,
        session: SessionDep,
        _: AuthDep,
        speaker: Annotated[str, Form()],
    ) -> JSONResponse:
        """Ручная правка роли реплики (doc 02 §2.3 п.3): правка пользователя
        сохраняется в labels (target_type=segment) и применяется к сегменту.
        speaker: agent | client."""
        if speaker not in ("agent", "client"):
            raise HTTPException(422, "speaker: agent | client")
        from polylog.models.calls import CallSegment
        from polylog.models.system import Label

        call = await session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "звонок не найден")
        seg = (
            (
                await session.execute(
                    select(CallSegment).where(
                        CallSegment.call_id == call_id, CallSegment.idx == idx
                    )
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
            )
        )
        await session.commit()
        return {"call_id": str(call_id), "idx": idx, "speaker": speaker}

    @app.post("/api/v1/calls/{call_id}/reprocess", response_model=CallOut)
    async def reprocess_call(call_id: uuid.UUID, session: SessionDep, settings: SettingsDep, _: AuthDep) -> CallOut:
        """Перезапуск пайплайна (failed → discovered → done), doc 01 §5.1."""
        call = await session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "звонок не найден")
        try:
            call = await process_call(session, call_id, settings, app.state.storage)
        except Exception as e:  # noqa: BLE001
            log.warning("репроцессинг %s упал: %s", call_id, e)
        await session.commit()
        await session.refresh(call)
        return _call_to_out(call)

    @app.get("/api/v1/contacts/{contact_id}/calls", response_model=CallList)
    async def contact_calls(contact_id: uuid.UUID, session: SessionDep, _: AuthDep) -> CallList:
        """Цепочка звонков контакта (thread_id/previous_call_id, doc 03 §4.1)."""
        rows = (
            (
                await session.execute(
                    select(Call)
                    .where(Call.contact_id == contact_id)
                    .order_by(Call.started_at, Call.id)
                )
            )
            .scalars()
            .all()
        )
        return CallList(total=len(rows), items=[_call_to_out(c) for c in rows])

    @app.get("/api/v1/contacts/search")
    async def contacts_search(
        session: SessionDep,
        _: AuthDep,
        q: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> JSONResponse:
        """Клиенты для Customer 360 (doc 03 §4). Без q — общий список всех
        контактов org (реестр). С q: цифры — подстрока номера (E.164),
        буквенная часть — подстрока имени контакта (из CRM)."""
        from polylog.models.graph import Contact, EntityLink, PhoneNumber

        org = await get_default_org(session)

        contact_ids: set[uuid.UUID] = set()
        if q is None or not q.strip():
            all_contacts = (
                (
                    await session.execute(
                        select(Contact)
                        .where(Contact.org_id == org.id)
                        .order_by(Contact.created_at.desc())
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )
            contact_ids = {c.id for c in all_contacts}
        else:
            if len(q) < 2:
                raise HTTPException(422, "q должен быть не короче 2 символов")
            digits = re.sub(r"\D+", "", q)
            if digits:
                phones = (
                    (
                        await session.execute(
                            select(PhoneNumber).where(
                                PhoneNumber.org_id == org.id,
                                PhoneNumber.e164.like(f"%{digits}%"),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if phones:
                    links = (
                        (
                            await session.execute(
                                select(EntityLink).where(
                                    EntityLink.org_id == org.id,
                                    EntityLink.src_type == "contact",
                                    EntityLink.dst_type == "phone_number",
                                    EntityLink.rel == "has_phone",
                                    EntityLink.dst_id.in_([str(p.id) for p in phones]),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    contact_ids.update(uuid.UUID(lnk.src_id) for lnk in links)
            if any(ch.isalpha() for ch in q):
                by_name = (
                    (
                        await session.execute(
                            select(Contact).where(
                                Contact.org_id == org.id,
                                Contact.display_name.ilike(f"%{q}%"),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                contact_ids.update(c.id for c in by_name)

        if not contact_ids:
            return JSONResponse({"items": []})

        links = (
            (
                await session.execute(
                    select(EntityLink).where(
                        EntityLink.org_id == org.id,
                        EntityLink.src_type == "contact",
                        EntityLink.dst_type == "phone_number",
                        EntityLink.rel == "has_phone",
                        EntityLink.src_id.in_([str(c) for c in contact_ids]),
                    )
                )
            )
            .scalars()
            .all()
        )
        phones_by_contact: dict[str, list[str]] = {}
        if links:
            phone_rows = (
                (
                    await session.execute(
                        select(PhoneNumber).where(
                            PhoneNumber.id.in_([uuid.UUID(lnk.dst_id) for lnk in links])
                        )
                    )
                )
                .scalars()
                .all()
            )
            e164_by_id = {str(p.id): p.e164 for p in phone_rows}
            for lnk in links:
                e164 = e164_by_id.get(lnk.dst_id)
                if e164:
                    phones_by_contact.setdefault(lnk.src_id, []).append(e164)

        contacts = (
            (await session.execute(select(Contact).where(Contact.id.in_(contact_ids))))
            .scalars()
            .all()
        )

        # Предиктивные метки реестра пачкой (те же правила scorecard M5, что в
        # /contacts/{id}/risk): days_silence, unanswered, unhandled, avg_score
        from sqlalchemy import case

        from polylog.models.calls import Objection, Score
        from polylog.risk.scorecard import AccountFeatures, scorecard

        now = datetime.now(UTC)
        call_stats = (
            (
                await session.execute(
                    select(
                        Call.contact_id,
                        func.count(),
                        func.max(Call.started_at),
                        func.sum(case((Call.duration_sec > 5, 1), else_=0)),
                        func.avg(Score.total),
                    )
                    .select_from(Call)
                    .outerjoin(Score, Score.call_id == Call.id)
                    .where(Call.org_id == org.id, Call.contact_id.in_(contact_ids))
                    .group_by(Call.contact_id)
                )
            )
            .all()
        )
        obj_stats = (
            (
                await session.execute(
                    select(
                        Call.contact_id,
                        func.count(Objection.id),
                        func.sum(case((Objection.response_status != "handled_success", 1), else_=0)),
                    )
                    .select_from(Call)
                    .join(Objection, Objection.call_id == Call.id)
                    .where(Call.org_id == org.id, Call.contact_id.in_(contact_ids))
                    .group_by(Call.contact_id)
                )
            )
            .all()
        )
        obj_map = {cid: (tot or 0, unhand or 0) for cid, tot, unhand in obj_stats}

        # Тренд тональности пачкой: сентимент последнего и первого звонка контакта
        from polylog.models.calls import CallMetrics

        sentiment_rows = (
            (
                await session.execute(
                    select(Call.contact_id, Call.started_at, CallMetrics.metrics)
                    .select_from(Call)
                    .join(CallMetrics, CallMetrics.call_id == Call.id)
                    .where(
                        Call.org_id == org.id,
                        Call.contact_id.in_(contact_ids),
                        CallMetrics.metrics.is_not(None),
                    )
                    .order_by(Call.started_at)
                )
            )
            .all()
        )
        sentiment_seq: dict[uuid.UUID, list[float]] = {}
        for cid, _st, metrics in sentiment_rows:
            cs = (metrics or {}).get("client_sentiment")
            if cs is not None and "score" in cs:
                sentiment_seq.setdefault(cid, []).append(float(cs["score"]))

        risk_by_contact: dict[uuid.UUID, dict] = {}
        avg_by_contact: dict[uuid.UUID, float | None] = {}
        agg_map: dict[uuid.UUID, tuple[int, datetime | None]] = {}
        for cid, cnt, last, answered, avg_sc in call_stats:
            agg_map[cid] = (cnt, last)
            total_obj, unhandled = obj_map.get(cid, (0, 0))
            if last is not None and last.tzinfo is None:  # sqlite возвращает naive
                last = last.replace(tzinfo=UTC)
            days_silence = max(0, (now - last).days) if last is not None else 0
            avg = round(float(avg_sc), 1) if avg_sc is not None else None
            avg_by_contact[cid] = avg
            if cnt:
                feats = AccountFeatures(
                    days_silence=days_silence,
                    unanswered_ratio=round(1 - (answered or 0) / cnt, 3),
                    # obj_map уже считает НЕотработанные (≠ handled_success)
                    unhandled_ratio=round(unhandled / total_obj, 3) if total_obj else 0.0,
                    avg_score=avg,
                    chain_depth=cnt,
                )
                risk_by_contact[cid] = scorecard(feats)

        items = []
        for c in contacts:
            cnt, last = agg_map.get(c.id, (0, None))
            last_iso = last.isoformat() if last is not None else None
            total_obj, unhandled = obj_map.get(c.id, (0, 0))
            sc = risk_by_contact.get(c.id)
            seq = sentiment_seq.get(c.id) or []
            items.append({
                "contact_id": str(c.id),
                "display_name": c.display_name,
                "phones": sorted(phones_by_contact.get(str(c.id), [])),
                "calls_total": cnt,
                "last_call_at": last_iso,
                "risk_score": sc["score"] if sc else None,
                "risk_band": sc["band"] if sc else None,
                "avg_score": avg_by_contact.get(c.id),
                "objections_unhandled": unhandled,
                "sentiment_last": seq[-1] if seq else None,
                "sentiment_trend": round(seq[-1] - seq[0], 3) if len(seq) > 1 else None,
            })
        # реестр/поиск: сверху клиенты с последней активностью, без звонков — в конце
        items.sort(key=lambda x: x["last_call_at"] or "", reverse=True)
        items.sort(key=lambda x: x["last_call_at"] is None)  # стабильно: активные выше
        return JSONResponse({"items": items[:limit]})

    @app.get("/api/v1/contacts/{contact_id}/card")
    async def contact_card(contact_id: uuid.UUID, session: SessionDep, _: AuthDep) -> JSONResponse:
        """Карточка Customer 360 (doc 03 §4, doc 08 §4.4): профиль + таймлайн
        (звонки и не-телефонные взаимодействия) + риск + похожие звонки."""
        from sqlalchemy import or_
        from sqlalchemy import text as sqltext

        from polylog.models.calls import Objection, Score
        from polylog.models.graph import Company, Contact, Deal, EntityLink, Interaction, PhoneNumber
        from polylog.risk import risk_for_contact

        contact = await session.get(Contact, contact_id)
        if contact is None:
            raise HTTPException(404, "контакт не найден")

        links = (
            (
                await session.execute(
                    select(EntityLink).where(
                        EntityLink.src_type == "contact",
                        EntityLink.dst_type == "phone_number",
                        EntityLink.rel == "has_phone",
                        EntityLink.src_id == str(contact.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        phones: list[str] = []
        if links:
            phone_rows = (
                (
                    await session.execute(
                        select(PhoneNumber).where(
                            PhoneNumber.id.in_([uuid.UUID(lnk.dst_id) for lnk in links])
                        )
                    )
                )
                .scalars()
                .all()
            )
            phones = sorted(p.e164 for p in phone_rows)

        company = None
        if contact.company_id is not None:
            comp = await session.get(Company, contact.company_id)
            if comp is not None:
                company = {"id": str(comp.id), "name": comp.name, "industry": comp.industry}

        deal_conds = [Deal.contact_id == contact.id]
        if contact.company_id is not None:
            deal_conds.append(Deal.company_id == contact.company_id)
        deals_rows = (
            (await session.execute(select(Deal).where(or_(*deal_conds)).order_by(Deal.created_at.desc())))
            .scalars()
            .all()
        )

        calls = (
            (
                await session.execute(
                    select(Call)
                    .where(Call.contact_id == contact.id)
                    .order_by(Call.started_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        call_ids = [c.id for c in calls]
        score_by_call: dict[uuid.UUID, Score] = {}
        objections_by_call: dict[uuid.UUID, list[Objection]] = {}
        if call_ids:
            for sc in (
                await session.execute(
                    select(Score).where(Score.call_id.in_(call_ids)).order_by(Score.created_at)
                )
            ).scalars().all():
                score_by_call[sc.call_id] = sc  # последний по created_at выигрывает
            for o in (
                await session.execute(select(Objection).where(Objection.call_id.in_(call_ids)))
            ).scalars().all():
                objections_by_call.setdefault(o.call_id, []).append(o)

        interactions = (
            (
                await session.execute(
                    select(Interaction)
                    .where(Interaction.contact_id == contact.id, Interaction.kind != "call")
                    .order_by(Interaction.occurred_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )

        risk = await risk_for_contact(session, contact.org_id, contact.id)

        # Похожие звонки: вектор последнего обработанного звонка, у которого
        # есть embedding (sqlite без pgvector → блок отсутствует)
        similar = None
        if session.bind and session.bind.url.get_backend_name().startswith("postgresql"):
            for c in calls[:5]:
                vec = (
                    await session.execute(
                        sqltext(
                            "SELECT vector::text FROM embeddings "
                            "WHERE entity_type='call' AND entity_id=:eid ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"eid": str(c.id)},
                    )
                ).first()
                if vec is None:
                    continue
                found = (
                    (
                        await session.execute(
                            sqltext(
                                """
                                SELECT e.entity_id, 1 - (e.vector <=> CAST(:qv AS halfvec)) AS sim,
                                       c.phone_from, c.phone_to, c.direction, c.started_at, c.duration_sec
                                FROM embeddings e JOIN calls c ON c.id::text = e.entity_id
                                WHERE e.entity_type='call' AND e.org_id=:org AND e.entity_id <> :eid
                                ORDER BY e.vector <=> CAST(:qv AS halfvec)
                                LIMIT 5
                                """
                            ),
                            {"qv": vec[0], "org": contact.org_id, "eid": str(c.id)},
                        )
                    )
                    .mappings()
                    .all()
                )
                similar = {
                    "base_call_id": str(c.id),
                    "items": [
                        {
                            "call_id": s["entity_id"],
                            "similarity": round(float(s["sim"]), 4),
                            # клиентский номер по направлению звонка
                            "phone": (s["phone_to"] if s["direction"] == "outbound" else s["phone_from"])
                            or s["phone_from"]
                            or s["phone_to"],
                            "started_at": s["started_at"].isoformat(),
                            "duration_sec": s["duration_sec"],
                        }
                        for s in found
                    ],
                }
                break

        # Сентимент по звонкам (метрика client_sentiment из пайплайна) + тренд
        from polylog.models.calls import CallMetrics

        sentiment_by_call: dict[uuid.UUID, dict] = {}
        if call_ids:
            for m in (
                await session.execute(select(CallMetrics).where(CallMetrics.call_id.in_(call_ids)))
            ).scalars().all():
                cs = (m.metrics or {}).get("client_sentiment")
                if cs is not None:
                    sentiment_by_call[m.call_id] = cs

        # сигналы последнего звонка — для Next Best Action
        last_call_signals: list[str] = []
        if calls:
            from polylog.models.calls import Signal

            last_call_signals = (
                (
                    await session.execute(
                        select(Signal.kind).where(Signal.call_id == calls[0].id)
                    )
                )
                .scalars()
                .all()
            )

        call_items = [
            {
                "id": str(c.id),
                "direction": c.direction,
                "phone_from": c.phone_from,
                "phone_to": c.phone_to,
                "started_at": c.started_at.isoformat(),
                "duration_sec": c.duration_sec,
                "state": c.state,
                "chain_depth": c.chain_depth,
                "score_total": score_by_call[c.id].total if c.id in score_by_call else None,
                "sentiment": sentiment_by_call[c.id]["score"] if c.id in sentiment_by_call else None,
                "objections": [
                    {
                        "type": o.type,
                        "response_status": o.response_status,
                        "start_ms": o.start_ms,
                    }
                    for o in objections_by_call.get(c.id, [])
                ],
            }
            for c in calls
        ]
        all_objections = [o for lst in objections_by_call.values() for o in lst]
        score_vals = [sc.total for sc in score_by_call.values()]

        # Повторяющиеся нерешённые проблемы (Root-Cause, DoD М3): тип возражения
        # в ≥2 разных звонках, последняя отработка — неуспешная
        from polylog.insights.repeat import find_repeats

        repeat_items = find_repeats(
            [
                (c.started_at, [(o.type, o.response_status) for o in objections_by_call.get(c.id, [])])
                for c in calls
            ]
        )

        stats = {
            "calls_total": len(calls),
            "done_calls": sum(1 for c in calls if c.state == "done"),
            "first_call_at": calls[-1].started_at.isoformat() if calls else None,
            "last_call_at": calls[0].started_at.isoformat() if calls else None,
            "avg_score": round(sum(score_vals) / len(score_vals), 1) if score_vals else None,
            "objections_total": len(all_objections),
            # согласовано со скоркардом: частичная отработка — не успех
            "objections_unhandled": sum(1 for o in all_objections if o.response_status != "handled_success"),
            "talk_sec_total": sum(c.duration_sec or 0 for c in calls),
            "sentiment_last": (
                sentiment_by_call[calls[0].id]["score"] if calls and calls[0].id in sentiment_by_call else None
            ),
            "sentiment_trend": (
                round(sentiment_by_call[calls[0].id]["score"] - sentiment_by_call[calls[-1].id]["score"], 3)
                if calls
                and calls[0].id in sentiment_by_call
                and calls[-1].id in sentiment_by_call
                and len(calls) > 1
                else None
            ),
        }

        # Next Best Action (DoD М3): правила на риске/повторах/последнем звонке
        from polylog.insights.nba import next_best_actions

        last_call_for_nba = (
            {
                "score_total": score_by_call[calls[0].id].total if calls[0].id in score_by_call else None,
                "objections": [
                    {"type": o.type, "response_status": o.response_status}
                    for o in objections_by_call.get(calls[0].id, [])
                ],
                "signals": last_call_signals,
            }
            if calls
            else None
        )
        nba_items = next_best_actions(
            risk,
            repeat_items,
            stats,
            last_call_for_nba,
            sentiment_by_call.get(calls[0].id) if calls else None,
        )

        return JSONResponse({
            "contact": {
                "id": str(contact.id),
                "display_name": contact.display_name,
                "created_at": contact.created_at.isoformat(),
            },
            "phones": phones,
            "company": company,
            "deals": [
                {
                    "id": str(d.id),
                    "stage": d.stage,
                    "amount": float(d.amount) if d.amount is not None else None,
                    "currency": d.currency,
                    "status": d.status,
                }
                for d in deals_rows
            ],
            "stats": stats,
            "calls": call_items,
            "interactions": [
                {
                    "id": str(i.id),
                    "kind": i.kind,
                    "occurred_at": i.occurred_at.isoformat(),
                    "payload": i.payload,
                }
                for i in interactions
            ],
            "risk": risk,
            "repeat": {"items": repeat_items},
            "nba": {"items": nba_items},
            "similar": similar,
        })

    @app.post("/api/v1/hooks/{connector}", status_code=status.HTTP_202_ACCEPTED)
    async def connector_hook(
        connector: str,
        request: Request,
        session: SessionDep,
        settings: SettingsDep,
        x_hook_signature: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        """Webhook-приём событий телефонии/CRM (doc 02 §1.1, doc 04 §1).

        Подпись: HMAC-SHA256 тела с секретом коннектора в заголовке X-Hook-Signature
        (hex); секрет per-коннектор, задаётся в настройках (prod).
        Поддержка: bitrix24, amocrm, mightycall (и любые генерящие CallRef-совместимые
        payload — парсер на стороне коннектора)."""
        from polylog.ingest.registry import get_connector

        body = await request.body()
        if not body:
            raise HTTPException(422, "пустой payload")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise HTTPException(422, f"payload не JSON: {e}") from e

        try:
            conn = get_connector(connector, {})
        except Exception:  # noqa: BLE001 — неизвестный коннектор → 404
            raise HTTPException(404, f"коннектор {connector!r} не зарегистрирован") from None

        # HMAC-проверка (если секрет настроен)

        secret = _hook_secret(connector)
        if secret:
            expected = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if not x_hook_signature or not hmac_mod.compare_digest(x_hook_signature, expected):
                raise HTTPException(401, "неверная подпись X-Hook-Signature")

        # парсинг payload: _WebhookOnly.parse (bitrix24) либо parse-функции модулей
        parse = getattr(conn, "parse", None)
        if parse is None:
            try:
                mod = sys.modules[conn.__class__.__module__]
            except KeyError:  # pragma: no cover
                raise HTTPException(422, f"коннектор {connector!r} не поддерживает webhook") from None
            parse = getattr(mod, "parse_call_element", None) or getattr(mod, "parse_call_json", None)
            if parse is None:
                raise HTTPException(422, f"коннектор {connector!r} не поддерживает webhook-приём")
        ref = parse(payload)
        if ref is None:
            return {"status": "skipped", "reason": "payload без звонка с записью"}

        org = await get_default_org(session)
        from polylog.ingest.service import get_or_create_connector

        connector_row = await get_or_create_connector(session, org.id, connector, {})
        call = await create_call_from_ref(session, org, connector_row, ref, app.state.storage, source="connector")
        created = call is not None
        if not created:
            call = (
                await session.execute(
                    select(Call).where(
                        Call.org_id == org.id,
                        Call.external_id == ref.external_id,
                        Call.connector_id == connector_row.id,
                    )
                )
            ).scalar_one()
        # пайплайн — только когда есть запись (звонки без записи ожидают
        # скачивания аудио коннектором/поллингом, doc 02 §1.1)
        if created and ref.recording_uri and settings.inline_process:
            try:
                call = await process_call(session, call.id, settings, app.state.storage)
            except Exception as e:  # noqa: BLE001 — стадия пометила failed
                log.warning("webhook-звонок %s: пайплайн упал: %s", call.id, e)
        await session.commit()
        await session.refresh(call)
        return {
            "status": "ok", "created": created,
            "call_id": str(call.id), "state": call.state,
            "reason": None if ref.recording_uri else "без записи — пайплайн отложен",
        }

    @app.get("/api/v1/calls/{call_id}/audio")
    async def call_audio(
        call_id: uuid.UUID,
        session: SessionDep,
        settings: SettingsDep,
        api_key: Annotated[str | None, Query()] = None,
    ):
        """Запись звонка для плеера. Токен — через ?api_key= (audio-элемент
        не умеет заголовки); доступ логируется в audit_log (doc 04 §5)."""
        from fastapi.responses import FileResponse

        if not api_key or not secrets_module.compare_digest(api_key, settings.api_token):
            raise HTTPException(401, "неверный api_key")
        call = await session.get(Call, call_id)
        if call is None or not call.recording_key:
            raise HTTPException(404, "звонок или запись не найдена")
        try:
            path = app.state.storage.path(call.recording_key)
        except StorageError:
            raise HTTPException(404, "запись не найдена в хранилище") from None
        from polylog.models.system import AuditLog

        session.add(AuditLog(action="audio_play", resource_type="call",
                             resource_id=str(call.id)))
        await session.commit()
        return FileResponse(path, media_type="audio/wav", filename=path.name)

    @app.get("/api/v1/stats/summary")
    async def stats_summary(
        session: SessionDep,
        _: AuthDep,
        days: Annotated[int, Query(ge=1, le=365)] = 30,
        date_from: Annotated[str | None, Query()] = None,
        date_to: Annotated[str | None, Query()] = None,
        duration_min: Annotated[int | None, Query(ge=0)] = None,
        duration_max: Annotated[int | None, Query(ge=0)] = None,
    ) -> JSONResponse:
        """Сводка для дашборда РОПа (doc 08 §4.1): объёмы, оценки, топ-возражения."""
        from datetime import timedelta

        from sqlalchemy import func

        from polylog.models.calls import Call, Objection, Score
        from polylog.models.enums import CallState

        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)
        conds = [Call.org_id == org.id, Call.started_at >= since]
        if date_from:
            conds.append(Call.started_at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
        if date_to:
            conds.append(Call.started_at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))
        if duration_min is not None:
            conds.append(Call.duration_sec >= duration_min)
        if duration_max is not None:
            conds.append(Call.duration_sec <= duration_max)

        total = (
            await session.execute(
                select(func.count()).select_from(Call).where(*conds)
            )
        ).scalar_one()
        done = (
            await session.execute(
                select(func.count()).select_from(Call)
                .where(*conds, Call.state == CallState.done.value)
            )
        ).scalar_one()
        avg_score = (
            await session.execute(
                select(func.avg(Score.total)).join(Call, Call.id == Score.call_id)
                .where(*conds)
            )
        ).scalar_one()
        top_objections = (
            (
                await session.execute(
                    select(Objection.type, func.count().label("cnt"))
                    .join(Call, Call.id == Objection.call_id)
                    .where(*conds)
                    .group_by(Objection.type)
                    .order_by(func.count().desc())
                    .limit(5)
                )
            ).all()
        )
        return JSONResponse({
            "period_days": days,
            "total_calls": total,
            "done_calls": done,
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
            "top_objections": [{"type": t, "count": c} for t, c in top_objections],
        })

    @app.get("/api/v1/contacts/{contact_id}/risk")
    async def contact_risk(
        contact_id: uuid.UUID, session: SessionDep, _: AuthDep
    ) -> JSONResponse:
        """Риск потери контакта (M5 scorecard, doc 08 §1): факторы-вклады +
        band; CatBoost+SHAP подключается после N≥30 исходов."""
        from polylog.graph.service import get_default_org
        from polylog.risk import risk_for_contact

        org = await get_default_org(session)
        result = await risk_for_contact(session, org.id, contact_id)
        if result is None:
            raise HTTPException(404, "у контакта нет звонков")
        return JSONResponse(result)

    @app.get("/api/v1/insights")
    async def list_insights(
        session: SessionDep,
        _: AuthDep,
        status_filter: Annotated[str | None, Query(alias="status")] = "new",
        severity: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> JSONResponse:
        """Лента инсайтов (doc 08 §4.2): risk_account и repeat_objection;
        фильтры status/severity; ack/dismiss меняют статус."""
        org = await get_default_org(session)
        conds = [Insight.org_id == org.id]
        if status_filter:
            conds.append(Insight.status == status_filter)
        if severity:
            conds.append(Insight.severity == severity)
        rows = (
            (
                await session.execute(
                    select(Insight).where(*conds).order_by(Insight.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return JSONResponse({
            "items": [
                {
                    "id": str(i.id),
                    "kind": i.kind,
                    "severity": i.severity,
                    "contact_id": str(i.contact_id) if i.contact_id else None,
                    "payload": i.payload,
                    "generated_by": i.generated_by,
                    "status": i.status,
                    "created_at": i.created_at.isoformat(),
                }
                for i in rows
            ]
        })

    @app.post("/api/v1/insights/{insight_id}/{action}")
    async def insight_action(
        insight_id: uuid.UUID,
        action: str,
        session: SessionDep,
        _: AuthDep,
    ) -> JSONResponse:
        """ack (принято, уходит из ленты) | dismiss (скрыто)."""
        if action not in ("ack", "dismiss"):
            raise HTTPException(422, "action: ack | dismiss")
        insight = await session.get(Insight, insight_id)
        if insight is None:
            raise HTTPException(404, "инсайт не найден")
        insight.status = "ack" if action == "ack" else "dismiss"
        await session.commit()
        return {"id": str(insight.id), "status": insight.status}

    @app.get("/api/v1/risks/top")
    async def risks_top(
        session: SessionDep,
        _: AuthDep,
        limit: Annotated[int, Query(ge=1, le=20)] = 5,
    ) -> JSONResponse:
        """Риск-борд РОПа (doc 08 §4.1): контакты, отсортированные по scorecard-риску.
        Периодическая джоба дублирует результаты в insights — тут пересчёт live."""
        from polylog.graph.service import get_default_org
        from polylog.risk import risk_for_contact

        org = await get_default_org(session)
        contact_ids = (
            (
                await session.execute(
                    select(Call.contact_id)
                    .where(Call.org_id == org.id, Call.contact_id.is_not(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        items = []
        for cid in contact_ids:
            r = await risk_for_contact(session, org.id, cid)
            if r is not None:
                recent = (
                    (
                        await session.execute(
                            select(Call.id)
                            .where(Call.org_id == org.id, Call.contact_id == cid)
                            .order_by(Call.started_at.desc())
                            .limit(5)
                        )
                    )
                    .scalars()
                    .all()
                )
                items.append({
                    "contact_id": str(cid),
                    "score": r["score"],
                    "band": r["band"],
                    "top_factor": r["factors"][0]["description"] if r["factors"] else "",
                    "factors": r["factors"][:3],
                    "calls_total": r.get("features", {}).get("calls_total"),
                    "recent_call_ids": [str(c) for c in recent],
                })
        items.sort(key=lambda x: -x["score"])
        return JSONResponse({"items": items[:limit], "total": len(items)})


    @app.get("/api/v1/insights/objection-clusters")
    async def objection_clusters(
        session: SessionDep,
        _: AuthDep,
        days: Annotated[int, Query(ge=1, le=365)] = 90,
        threshold: Annotated[float, Query(ge=0.5, le=0.99)] = 0.82,
    ) -> JSONResponse:
        """Кластеры похожих возражений (objection_pattern, doc 02 §5): эмбеддинги
        цитат → greedy-кластеризация → группы с representative-цитатами.
        Группировка читается РОПом для пополнения таксономии/скриптов."""
        from datetime import timedelta

        from sqlalchemy import or_

        from polylog.embeddings import EmbeddingBackend
        from polylog.insights.clustering import cluster_items
        from polylog.models.calls import Call, Objection

        org = await get_default_org(session)
        since = datetime.now(UTC) - timedelta(days=days)
        rows = (
            (
                await session.execute(
                    select(
                        Objection.span_text,
                        Objection.type,
                        Objection.call_id,
                        Call.phone_from,
                        Call.phone_to,
                        Call.started_at,
                        Call.direction,
                    )
                    .join(Call, Call.id == Objection.call_id)
                    .where(
                        Call.org_id == org.id,
                        Call.started_at >= since,
                        # short_call (<15 c) исключён из семантического анализа (DoD М1)
                        or_(Call.duration_sec.is_(None), Call.duration_sec >= 15),
                    )
                    .limit(2000)
                )
            )
            .all()
        )
        if not rows:
            return JSONResponse({"period_days": days, "clusters": [], "total": 0})

        backend = EmbeddingBackend()
        vectors = backend.embed([r[0] for r in rows])
        items = [
            {
                "vector": v,
                "text": txt,
                "type": ty,
                "call_id": str(cid),
                # клиентский номер: у исходящего — phone_to, у входящего — phone_from
                "phone": (pt if direction == "outbound" else pf) or pf or pt,
                "started_at": st.isoformat(),
            }
            for v, (txt, ty, cid, pf, pt, st, direction) in zip(vectors, rows, strict=True)
        ]
        call_info = {it["call_id"]: (it["phone"], it["started_at"]) for it in items}
        clusters = cluster_items(items, threshold=threshold)
        out = []
        for c in clusters[:20]:
            d = c.as_dict()
            member_calls = list(dict.fromkeys(items[i]["call_id"] for i in c.members))
            d["calls"] = [
                {"call_id": cid, "phone": call_info[cid][0], "started_at": call_info[cid][1]}
                for cid in member_calls[:8]
            ]
            out.append(d)
        return JSONResponse({
            "period_days": days,
            "threshold": threshold,
            "total_objections": len(rows),
            "clusters": out,
        })

    @app.get("/api/v1/search/similar")
    async def search_similar(
        call_id: uuid.UUID,
        session: SessionDep,
        _: AuthDep,
        limit: Annotated[int, Query(ge=1, le=20)] = 5,
    ) -> JSONResponse:
        """Семантический поиск похожих звонков (M9, doc 08 §1): kNN по вектору
        звонка в pgvector (cosine). Требует Postgres + выполненный embed."""
        if not session.bind or not session.bind.url.get_backend_name().startswith("postgresql"):
            raise HTTPException(501, "поиск требует Postgres (pgvector)")
        call = await session.get(Call, call_id)
        if call is None:
            raise HTTPException(404, "звонок не найден")
        from sqlalchemy import text as sqltext

        row = (
            await session.execute(
                sqltext(
                    "SELECT vector::text FROM embeddings "
                    "WHERE entity_type='call' AND entity_id=:eid ORDER BY created_at DESC LIMIT 1"
                ),
                {"eid": str(call_id)},
            )
        ).first()
        if row is None:
            raise HTTPException(409, "у звонка нет вектора — прогрейте embed (embed_backfill.py)")
        similar = (
            (
                await session.execute(
                    sqltext(
                        """
                        SELECT e.entity_id, 1 - (e.vector <=> CAST(:qv AS halfvec)) AS sim,
                               c.phone_from, c.phone_to, c.direction, c.started_at, c.duration_sec
                        FROM embeddings e JOIN calls c ON c.id::text = e.entity_id
                        WHERE e.entity_type='call' AND e.org_id=:org AND e.entity_id <> :eid
                        ORDER BY e.vector <=> CAST(:qv AS halfvec)
                        LIMIT :lim
                        """
                    ),
                    {"qv": row[0], "org": call.org_id, "eid": str(call_id), "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return JSONResponse({
            "call_id": str(call_id),
            "items": [
                {
                    "call_id": s["entity_id"],
                    "similarity": round(float(s["sim"]), 4),
                    # клиентский номер: у исходящего — phone_to, у входящего — phone_from
                    "phone": (s["phone_to"] if s["direction"] == "outbound" else s["phone_from"])
                    or s["phone_from"]
                    or s["phone_to"],
                    "started_at": s["started_at"].isoformat(),
                    "duration_sec": s["duration_sec"],
                }
                for s in similar
            ],
        })

    @app.exception_handler(StorageError)
    async def storage_error_handler(request, exc: StorageError) -> JSONResponse:
        log.error("ошибка хранилища: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "внутренняя ошибка хранилища"})

    return app


def _looks_stereo(audio: bytes) -> bool:
    """Грубая проверка WAV-заголовка на 2 канала (для channels_hint при upload)."""
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return False
    try:
        channels = int.from_bytes(audio[22:24], "little")
    except Exception:  # noqa: BLE001
        return False
    return channels == 2


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("polylog.api.main:app", host="127.0.0.1", port=8000, reload=False)
