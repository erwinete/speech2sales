"""Роутер настроек: рубрики скоринга, словарь, org-настройки, 152-ФЗ (эразура), аудит."""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from sqlalchemy import select

from polylog.api.deps import AdminDep, AuthDep, SessionDep
from polylog.api.schemas.settings import LexiconEntryCreate, RubricUpdate
from polylog.models.calls import Call, CallMetrics, CallSegment, Objection, PIIFinding, Score, Signal, Violation
from polylog.models.system import AuditLog, LexiconEntry, ModelRegistry, Org, Rubric

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _audit(session, actor, action: str, resource_type: str, resource_id: str, details: dict | None = None) -> None:
    session.add(
        AuditLog(
            org_id=actor.org_id, actor_id=actor.user_id, action=action,
            resource_type=resource_type, resource_id=resource_id, details=details,
        )
    )


@router.get("/rubrics")
async def list_rubrics(session: SessionDep, _: AuthDep) -> dict:
    org = await _org(session)
    rows = (
        (
            await session.execute(
                select(Rubric).where(Rubric.org_id == org.id).order_by(Rubric.version.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        from polylog.scoring.engine import DEFAULT_RUBRIC_SPEC

        row = Rubric(
            org_id=org.id, name=DEFAULT_RUBRIC_SPEC["rubric_id"],
            version=DEFAULT_RUBRIC_SPEC["version"], spec=DEFAULT_RUBRIC_SPEC, is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        rows = [row]
    return {
        "items": [
            {
                "id": str(r.id), "name": r.name, "description": r.description,
                "version": r.version, "is_active": r.is_active,
                "spec": r.spec, "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def _org(session) -> Org:
    from polylog.graph.service import get_default_org

    return await get_default_org(session)


@router.put("/rubrics/active")
async def update_active_rubric(body: RubricUpdate, session: SessionDep, actor: AdminDep) -> dict:

    org = await _org(session)
    spec = body.spec
    if not isinstance(spec, dict) or not spec.get("items"):
        raise HTTPException(422, "spec.items обязателен")
    total_weight = sum(int(it.get("weight", 0)) for it in spec["items"])
    if total_weight != 100:
        raise HTTPException(422, f"сумма весов пунктов должна быть 100, сейчас {total_weight}")
    prev = (
        (
            await session.execute(
                select(Rubric)
                .where(Rubric.org_id == org.id, Rubric.is_active.is_(True))
                .order_by(Rubric.version.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    new_version = (prev.version + 1) if prev else 1
    # деактивируем прежние версии
    for r in (
        (await session.execute(select(Rubric).where(Rubric.org_id == org.id, Rubric.is_active.is_(True))))
        .scalars()
        .all()
    ):
        r.is_active = False
    row = Rubric(
        org_id=org.id, name=body.name, description=body.description,
        version=new_version, is_active=True, spec=spec, created_by=actor.user_id,
    )
    session.add(row)
    await session.flush()
    _audit(session, actor, "rubric_update", "rubric", str(row.id), {"version": new_version})

    rescored = 0
    if body.rescore_days:
        # пересчёт скоринга по звонкам за период (упрощённо: повторный stage_score)
        from polylog.config import get_settings as _gs
        from polylog.pipeline import stage_score

        settings = _gs()
        cutoff = datetime.now(UTC) - __import__("datetime").timedelta(days=body.rescore_days)
        call_rows = (
            (
                await session.execute(
                    select(Call).where(Call.org_id == org.id, Call.started_at >= cutoff)
                )
            )
            .scalars()
            .all()
        )
        for c in call_rows:
            try:
                await stage_score(session, c, None, settings)
                rescored += 1
            except Exception:  # noqa: BLE001 — звонок без анализа пропускается
                continue
    await session.commit()
    return {"id": str(row.id), "version": new_version, "rescored": rescored}


@router.get("/lexicon")
async def list_lexicon(session: SessionDep, _: AuthDep, category: str | None = None, q: str | None = None) -> dict:
    org = await _org(session)
    conds = [LexiconEntry.org_id == org.id]
    if category:
        conds.append(LexiconEntry.category == category)
    if q:
        conds.append(LexiconEntry.term.ilike(f"%{q}%"))
    rows = (
        (await session.execute(select(LexiconEntry).where(*conds).order_by(LexiconEntry.term)))
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(r.id), "term": r.term, "aliases": r.aliases or [],
                "phonetic_key": r.phonetic_key, "category": r.category,
                "case_sensitive": r.case_sensitive, "enabled": r.enabled,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/lexicon")
async def create_lexicon(body: LexiconEntryCreate, session: SessionDep, actor: AdminDep) -> dict:
    org = await _org(session)
    row = LexiconEntry(
        org_id=org.id, term=body.term, aliases=body.aliases,
        phonetic_key=body.phonetic_key, category=body.category,
        case_sensitive=body.case_sensitive, enabled=body.enabled,
    )
    session.add(row)
    await session.flush()
    _audit(session, actor, "lexicon_create", "lexicon", str(row.id), {"term": body.term})
    await session.commit()
    return {"id": str(row.id), "term": row.term}


@router.patch("/lexicon/{entry_id}")
async def update_lexicon(entry_id: uuid.UUID, body: LexiconEntryCreate, session: SessionDep, actor: AdminDep) -> dict:
    row = await session.get(LexiconEntry, entry_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404, "запись не найдена")
    row.term, row.aliases = body.term, body.aliases
    row.phonetic_key, row.category = body.phonetic_key, body.category
    row.case_sensitive, row.enabled = body.case_sensitive, body.enabled
    _audit(session, actor, "lexicon_update", "lexicon", str(row.id))
    await session.commit()
    return {"id": str(row.id)}


@router.delete("/lexicon/{entry_id}")
async def delete_lexicon(entry_id: uuid.UUID, session: SessionDep, actor: AdminDep) -> dict:
    row = await session.get(LexiconEntry, entry_id)
    if row is None or row.org_id != actor.org_id:
        raise HTTPException(404, "запись не найдена")
    await session.delete(row)
    _audit(session, actor, "lexicon_delete", "lexicon", str(entry_id))
    await session.commit()
    return {"id": str(entry_id), "deleted": True}


@router.post("/lexicon/import-csv")
async def import_lexicon_csv(session: SessionDep, actor: AdminDep, file: UploadFile = File(...)) -> dict:
    """Импорт словаря из CSV: columns term,aliases,category,case_sensitive."""
    import csv as csv_mod
    import io

    org = await _org(session)
    raw = (await file.read()).decode("utf-8-sig")
    created = 0
    reader = csv_mod.DictReader(io.StringIO(raw))
    for r in reader:
        term = (r.get("term") or "").strip()
        if not term:
            continue
        aliases = [a.strip() for a in (r.get("aliases") or "").split(";") if a.strip()]
        row = LexiconEntry(
            org_id=org.id, term=term, aliases=aliases,
            category=(r.get("category") or "").strip() or None,
            case_sensitive=(r.get("case_sensitive") or "").lower() in ("1", "true", "yes"),
            enabled=True,
        )
        session.add(row)
        created += 1
    _audit(session, actor, "lexicon_import", "lexicon", "csv", {"created": created})
    await session.commit()
    return {"created": created}


@router.get("/settings/org")
async def get_org_settings(session: SessionDep, _: AuthDep) -> dict:
    from polylog.asr.base import _FACTORIES

    org = await _org(session)
    from polylog.config import get_settings as _gs

    settings = _gs()
    return {
        "org": {"name": org.name, "settings": org.settings, "retention_policy": org.retention_policy},
        "pipeline": {
            "asr_backend": settings.asr_backend,
            "asr_backends_available": sorted(_FACTORIES.keys()),
            "pii_action": settings.pii_action,
            "pii_export_action": settings.pii_export_action,
            "diarization_enabled": settings.__dict__.get("diarization", None) is not None,
            "nli_enabled": bool(settings.nli_model_dir),
            "short_call_sec": 15,
        },
    }


@router.patch("/settings/org")
async def update_org_settings(session: SessionDep, actor: AdminDep, body: dict) -> dict:
    org = await _org(session)
    if "name" in body:
        org.name = body["name"]
    if "settings" in body:
        merged = dict(org.settings or {})
        merged.update(body["settings"])
        org.settings = merged
    if "retention_policy" in body:
        merged = dict(org.retention_policy or {})
        merged.update(body["retention_policy"])
        org.retention_policy = merged
    _audit(session, actor, "org_settings_update", "org", str(org.id), body)
    await session.commit()
    return {"name": org.name, "settings": org.settings, "retention_policy": org.retention_policy}


@router.post("/privacy/erase-subject")
async def erase_subject(request: Request, session: SessionDep, actor: AdminDep, body: dict) -> dict:
    """Эразура субъекта ПДн по 152-ФЗ (docs/04 §4): удаление аудио/сегментов/
    векторов + обезличивание номеров, акт в audit_log."""
    import os

    from polylog.models.graph import PhoneNumber

    org = await _org(session)
    phone = body.get("phone")
    contact_id = body.get("contact_id")
    reason = body.get("reason", "")
    if not phone and not contact_id:
        raise HTTPException(422, "нужен phone или contact_id")

    from polylog.models.graph import Contact as Contact_
    from polylog.models.graph import EntityLink

    conds = [Contact_.org_id == org.id]
    if contact_id:
        conds.append(Contact_.id == uuid.UUID(contact_id))

    contacts = (
        (await session.execute(select(Contact_).where(*conds))).scalars().all()
    )
    if phone:
        # контакты по номеру через граф
        phones = (
            (
                await session.execute(
                    select(PhoneNumber).where(PhoneNumber.org_id == org.id, PhoneNumber.e164 == phone)
                )
            )
            .scalars()
            .all()
        )
        for p in phones:
            links = (
                (
                    await session.execute(
                        select(EntityLink).where(
                            EntityLink.org_id == org.id,
                            EntityLink.dst_type == "phone_number",
                            EntityLink.dst_id == str(p.id),
                            EntityLink.rel == "has_phone",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for lnk in links:
                contacts.append(await session.get(Contact_, uuid.UUID(lnk.src_id)))

    erased_calls = erased_audio = erased_segments = 0
    storage = request.app.state.storage
    for contact in {c.id: c for c in contacts if c}.values():
        calls = (
            (
                await session.execute(
                    select(Call).where(Call.org_id == org.id, Call.contact_id == contact.id)
                )
            )
            .scalars()
            .all()
        )
        for c in calls:
            if c.recording_key and storage is not None:
                try:
                    if storage.exists(c.recording_key):
                        os.remove(storage.path(c.recording_key))
                        erased_audio += 1
                except OSError:
                    pass
            erased_segments += (
                await session.execute(
                    CallSegment.__table__.delete().where(CallSegment.call_id == c.id)
                )
            ).rowcount or 0
            for table in (Objection, Signal, Violation, PIIFinding, CallMetrics, Score):
                await session.execute(table.__table__.delete().where(table.call_id == c.id))
            # обезличивание номеров
            for f in ("phone_from", "phone_to"):
                val = getattr(c, f)
                if val:
                    setattr(c, f, "erased-" + hashlib.sha256(val.encode()).hexdigest()[:12])
            erased_calls += 1
        contact.display_name = None
    # обезличить phone_numbers
    if phone:
        for p in (
            (
                await session.execute(
                    select(PhoneNumber).where(PhoneNumber.org_id == org.id, PhoneNumber.e164 == phone)
                )
            )
            .scalars()
            .all()
        ):
            p.e164 = "erased-" + hashlib.sha256(phone.encode()).hexdigest()[:12]

    audit = AuditLog(
        org_id=org.id, actor_id=actor.user_id, action="subject_erasure",
        resource_type="contact", resource_id=contact_id or phone,
        details={"reason": reason, "erased_calls": erased_calls},
    )
    session.add(audit)
    await session.flush()
    await session.commit()
    return {
        "erased_calls": erased_calls,
        "erased_audio_files": erased_audio,
        "erased_segments": erased_segments,
        "audit_id": audit.id,
        "completed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/audit")
async def list_audit(
    session: SessionDep,
    _: AdminDep,
    action: str | None = None,
    resource_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    org = await _org(session)
    conds = [AuditLog.org_id == org.id]
    if action:
        conds.append(AuditLog.action == action)
    if resource_type:
        conds.append(AuditLog.resource_type == resource_type)
    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(*conds)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/settings/models/train-risk")
async def train_risk_model(session: SessionDep, _: AdminDep) -> dict:
    """V5-04 (ТЗ v5.0 §9.1): авто-обучение CatBoost по закрытым сделкам
    (won/lost) с регистрацией в models_registry. 422 — исходов меньше N_MIN."""
    from polylog.risk.model import N_MIN_OUTCOMES, train_from_db

    org = await _org(session)  # noqa: F841 — скоуп будущих фильтров обучения
    try:
        result = await train_from_db(session, org.id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(422, str(e)) from e
    await session.commit()
    return {"status": "trained", "n_min": N_MIN_OUTCOMES, **result}


@router.get("/settings/models")
async def list_models_registry(session: SessionDep, _: AuthDep) -> dict:
    """Модели в реестре (V5-04): статус обучения риск-модели."""
    rows = (
        (
            await session.execute(
                select(ModelRegistry).where(ModelRegistry.status == "active")
                .order_by(ModelRegistry.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": str(m.id),
                "kind": m.kind,
                "model_id": m.model_id,
                "version": m.version,
                "dim": m.dim,
                "params": m.params,
                "status": m.status,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
    }
