"""Роутер экспорта (V5-03, ТЗ v5.0 §9.2-3): Слой B — сценарии тренажёра
возражений (TrainerScenario) и история выгрузок ExportJob."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from polylog.api.deps import CurrentUser, SessionDep, require_role
from polylog.export.artifact import build_call_artifact  # noqa: F401 — reexport для совместимости
from polylog.export.scenario import build_trainer_scenario, scenario_to_yaml
from polylog.models.calls import Call, Objection, Score
from polylog.models.system import AuditLog, ExportJob
from polylog.storage import StorageError  # noqa: F401

router = APIRouter(prefix="/api/v1", tags=["exports"])

RequireAnalyst = Annotated[CurrentUser, Depends(require_role("admin", "supervisor", "analyst"))]


def _org(session):
    from polylog.graph.service import get_default_org

    return get_default_org(session)


async def _save_export_job(session, org_id, user_id, kind: str, filter_spec: dict, scenario: dict) -> ExportJob:
    job = ExportJob(
        org_id=org_id, kind=kind, filter_spec=filter_spec,
        status="done", file_key=f"scenario:{scenario['scenario_id']}",
    )
    session.add(job)
    session.add(
        AuditLog(org_id=org_id, actor_id=user_id, action="export_scenario",
                 resource_type="export_job", resource_id=str(job.id),
                 details={"scenario_id": scenario["scenario_id"], "kind": kind}))
    return job


def _scenario_response(scenario: dict, fmt: str, filename: str) -> Response:
    if fmt == "yaml":
        return Response(
            content=scenario_to_yaml(scenario),
            media_type="application/x-yaml",
            headers={"Content-Disposition": f'attachment; filename="{filename}.yaml"'},
        )
    return JSONResponse(
        scenario,
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
    )


@router.get("/calls/{call_id}/scenario")
async def call_scenario(
    call_id: uuid.UUID,
    session: SessionDep,
    user: RequireAnalyst,
    fmt: Annotated[str, Query(pattern="^(json|yaml)$")] = "json",
    pii_policy: str = "mask",
) -> Response:
    """Сценарий тренажёра из конкретного звонка (V5-03): возражения с реальными
    цитатами (очищенными) + success_criteria из активной рубрики; пишется в
    ExportJob."""
    from polylog.graph.service import get_default_org

    org = await get_default_org(session)
    call = await session.get(Call, call_id)
    if call is None or call.org_id != org.id:
        raise HTTPException(404, "звонок не найден")
    objections = (
        (await session.execute(select(Objection).where(Objection.call_id == call_id)))
        .scalars()
        .all()
    )
    scores = (
        (
            await session.execute(
                select(Score).where(Score.call_id == call_id).order_by(Score.created_at.desc()).limit(1)
            )
        )
        .scalars()
        .all()
    )
    scenario = build_trainer_scenario(
        call_id=str(call_id),
        objections=[
            {"type": o.type, "span_text": o.span_text,
             "response_span": o.response_span, "confidence": o.confidence}
            for o in objections
        ],
        scores=[{"items": sc.items} for sc in scores],
        pii_policy=pii_policy,
    )
    await _save_export_job(session, org.id, user.user_id, "scenario",
                           {"call_id": str(call_id)}, scenario)
    await session.commit()
    return _scenario_response(scenario, fmt, f"scenario-{scenario['scenario_id']}")


class ClusterScenarioBody(BaseModel):
    days: int = 90
    limit: int = 10
    objection_type: str | None = None
    pii_policy: str = "mask"


@router.post("/exports/scenario-from-cluster")
async def scenario_from_cluster(
    body: ClusterScenarioBody, session: SessionDep, user: RequireAnalyst
) -> Response:
    """Сценарий тренажёра из кластера возражений (V5-03): цитаты неотработанных
    возражений за период; source_call_ids — звонки, где возражения звучали."""
    from polylog.graph.service import get_default_org

    org = await get_default_org(session)
    conds = [Objection.call_id == Call.id, Call.org_id == org.id]
    if body.objection_type:
        conds.append(Objection.type == body.objection_type)
    rows = (
        (
            await session.execute(
                select(Objection, Call.id)
                .where(*conds)
                .order_by(Objection.confidence.desc())
                .limit(max(1, body.limit) * 3)
            )
        )
        .all()
    )
    if not rows:
        raise HTTPException(404, "возражения за период не найдены")
    call_ids: list[str] = []
    objections: list[dict] = []
    for o, cid in rows:
        if str(cid) not in call_ids:
            call_ids.append(str(cid))
        if len(objections) < body.limit:
            objections.append({
                "type": o.type, "span_text": o.span_text,
                "response_span": o.response_span, "confidence": o.confidence,
            })
    scenario_id = f"cluster-{uuid.uuid4().hex[:12]}"
    scenario = build_trainer_scenario(
        call_id=scenario_id,
        objections=objections,
        scores=None,
        pii_policy=body.pii_policy,
    )
    scenario["scenario_id"] = scenario_id
    scenario["title"] = f"Кластер возражений «{objections[0]['type']}» — {len(objections)} реальных формулировок"
    scenario["metadata"]["source_call_ids"] = call_ids
    await _save_export_job(session, org.id, user.user_id, "scenario_from_cluster",
                           {"days": body.days, "calls": len(call_ids)}, scenario)
    await session.commit()
    return _scenario_response(scenario, "json", f"scenario-{scenario_id}")


@router.get("/exports")
async def exports_history(
    session: SessionDep, _: RequireAnalyst, limit: Annotated[int, Query(le=100)] = 20
) -> JSONResponse:
    """История выгрузок ExportJob (V5-03)."""
    from polylog.graph.service import get_default_org

    org = await get_default_org(session)
    rows = (
        (
            await session.execute(
                select(ExportJob)
                .where(ExportJob.org_id == org.id)
                .order_by(ExportJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return JSONResponse({
        "items": [
            {
                "id": str(j.id),
                "kind": j.kind,
                "filter_spec": j.filter_spec,
                "status": j.status,
                "file_key": j.file_key,
                "created_at": j.created_at.isoformat(),
            }
            for j in rows
        ]
    })
