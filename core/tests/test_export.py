"""Экспорт обменного формата: артефакт валиден по JSON-схеме v1.0 (doc 05)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from conftest import wav_bytes

from polylog.export.artifact import build_call_artifact, validate_artifact
from polylog.graph.service import get_default_org
from polylog.ingest.base import CallRef
from polylog.ingest.service import create_call_from_ref
from polylog.pipeline import process_call
from polylog.storage import LocalStorage

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas" / "call-artifacts.schema.json").read_text(
        encoding="utf-8"
    )
)


async def _processed_call(session, tmp_path: Path):
    from polylog.config import Settings

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/e.db",
        storage_dir=str(tmp_path / "storage"),
        tmp_dir=str(tmp_path / "tmp"),
        api_token="t",
        asr_backend="stub",
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    storage = LocalStorage(settings.storage_dir)
    org = await get_default_org(session)
    ref = CallRef(
        external_id="ex-1", started_at=datetime(2026, 10, 1, tzinfo=UTC),
        direction="outbound", phone_from="101", phone_to="+79001234567",
        recording_uri="q-101-9-out.wav", consent_flag=True,
    )
    call = await create_call_from_ref(session, org, None, ref, storage, audio=wav_bytes(6.0), source="devstand")
    assert call is not None
    wav_path = storage.path(call.recording_key)
    Path(wav_path).with_name(Path(wav_path).stem + ".transcript.json").write_text(
        json.dumps([
            {"speaker": "agent", "start_ms": 0, "end_ms": 2000,
             "text": "Добрый день, компания Ромашка, меня зовут Ирина."},
            {"speaker": "client", "start_ms": 2200, "end_ms": 4500,
             "text": "Здравствуйте! Сколько стоит подписка? Перезвоните на +7 900 111-22-33."},
            {"speaker": "agent", "start_ms": 4700, "end_ms": 5800,
             "text": "Скажу после уточнения объёма, давайте сравним условия."},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    call = await process_call(session, call.id, settings, storage)
    await session.commit()
    await session.refresh(call)
    return call, settings


async def test_artifact_validates_against_schema(session, tmp_path: Path):
    call, settings = await _processed_call(session, tmp_path)

    artifact = build_call_artifact(
        call=call,
        segments=call.segments,
        metrics=call.metrics.metrics if call.metrics else None,
        objections=call.objections,
        signals=call.signals,
        scores=[{"rubric_id": "default_b2b_v1", "rubric_version": 1, "total": 55.0, "items": []}],
        pii_policy="mask",
    )
    errors = validate_artifact(artifact, SCHEMA)
    assert errors == [], "\n".join(errors)

    assert artifact["schema_version"] == "1.0.0"
    assert artifact["generator"]["product"] == "polylog"
    assert artifact["call"]["call_id"] == str(call.id)
    assert artifact["call"]["previous_call_id"] is None and artifact["call"]["chain_depth"] == 0
    assert artifact["risk"]["abstained"] is True
    assert artifact["provenance"]["pii_policy"] == "mask"


async def test_artifact_masks_pii_in_export(session, tmp_path: Path):
    """PII (телефон в транскрипте) маскируется при экспорте (doc 04 §3, doc 05)."""
    call, settings = await _processed_call(session, tmp_path)
    artifact = build_call_artifact(
        call=call,
        segments=call.segments,
        metrics=None,
        objections=call.objections,
        signals=call.signals,
        scores=[],
        pii_policy="mask",
    )
    raw = json.dumps(artifact, ensure_ascii=False)
    assert "+7 900 111-22-33" not in raw and "89001112233" not in raw
    assert artifact["transcript"][1]["text"]


async def test_call_has_objections_and_score_after_pipeline(session, tmp_path: Path):
    call, _ = await _processed_call(session, tmp_path)
    assert call.objections[0].type == "price"
