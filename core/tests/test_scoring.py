"""Скоринг: rubric-engine с evidence + сквозной прогон пайплайна со скором."""

import json
from datetime import UTC, datetime
from pathlib import Path

from conftest import wav_bytes

from polylog.graph.service import get_default_org
from polylog.ingest.base import CallRef
from polylog.ingest.service import create_call_from_ref
from polylog.models.calls import Score
from polylog.models.enums import CallState
from polylog.pipeline import process_call
from polylog.scoring.engine import DEFAULT_RUBRIC_SPEC, evaluate
from polylog.storage import LocalStorage


def test_evaluate_full_success_call():
    segments = [
        {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 3000,
         "text": "Добрый день, компания Ромашка, меня зовут Ирина. Какие объёмы у вас в месяц?"},
        {"idx": 1, "speaker": "client", "start_ms": 3200, "end_ms": 6000,
         "text": "Порядка 200 единиц. Сколько это будет стоить?"},
        {"idx": 2, "speaker": "agent", "start_ms": 6200, "end_ms": 9500,
         "text": "Зависит от объёма, давайте сравним условия — при вашем объёме цена будет выгоднее."},
        {"idx": 3, "speaker": "client", "start_ms": 9700, "end_ms": 12000,
         "text": "Звучит интересно, расскажите подробнее и давайте созвонимся в четверг."},
        {"idx": 4, "speaker": "agent", "start_ms": 12200, "end_ms": 15000,
         "text": "Договорились! До свидания."},
    ]
    from polylog.nlp.rules import detect_findings

    findings = detect_findings(segments)
    metrics = {"agent_questions": 2}
    result = evaluate(DEFAULT_RUBRIC_SPEC, segments=segments, metrics=metrics, findings=findings)

    assert result["total"] == result["max_score"]  # образцовый звонок — максимум
    by_id = {it["item_id"]: it for it in result["items"]}
    assert by_id["greeting"]["score"] == 10
    assert by_id["greeting"]["evidence"][0]["start_ms"] == 0
    assert by_id["objections"]["score"] == 20
    assert by_id["next_step"]["score"] == 15
    assert by_id["next_step"]["evidence"][0]["span"]


def test_evaluate_weak_call_scores_low():
    segments = [
        {"idx": 0, "speaker": "agent", "start_ms": 0, "end_ms": 3000, "text": "Алё, слушаю."},
        {"idx": 1, "speaker": "client", "start_ms": 3200, "end_ms": 6000, "text": "Сколько стоит?"},
        {"idx": 2, "speaker": "agent", "start_ms": 6200, "end_ms": 9000,
         "text": "Пять тысяч. Гарантирую 100% результат."},
    ]
    from polylog.nlp.rules import detect_findings

    findings = detect_findings(segments)
    result = evaluate(DEFAULT_RUBRIC_SPEC, segments=segments, metrics={}, findings=findings)
    assert result["total"] < 30
    by_id = {it["item_id"]: it for it in result["items"]}
    assert by_id["greeting"]["score"] == 0
    assert by_id["forbidden"]["score"] == 0  # есть нарушение
    assert by_id["forbidden"]["explanation"]


async def test_pipeline_scores_call_with_sidecar(session, tmp_path: Path):
    """E2E: звонок с sidecar-транскриптом → analyzed → scored → done; Score в БД."""
    from polylog.config import Settings

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/s.db",
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
        external_id="sc-1", started_at=datetime(2026, 10, 1, tzinfo=UTC),
        direction="outbound", phone_from="101", phone_to="+79001234567",
        recording_uri="q-101-1-out.wav", consent_flag=True,
    )
    audio = wav_bytes(6.0)
    call = await create_call_from_ref(session, org, None, ref, storage, audio=audio, source="devstand")
    assert call is not None
    # sidecar рядом с сохранённым аудио (stub подхватит)
    wav_path = storage.path(call.recording_key)
    Path(wav_path).with_name(Path(wav_path).stem + ".transcript.json").write_text(
        json.dumps([
            {"speaker": "agent", "start_ms": 0, "end_ms": 2000,
             "text": "Добрый день, компания Ромашка, меня зовут Ирина. Какие объёмы у вас?"},
            {"speaker": "client", "start_ms": 2200, "end_ms": 4000,
             "text": "Здравствуйте! У нас уже есть поставщик."},
            {"speaker": "agent", "start_ms": 4200, "end_ms": 5800,
             "text": "Понимаю, давайте сравним условия по цене — будет выгоднее."},
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    call = await process_call(session, call.id, settings, storage)
    await session.commit()
    await session.refresh(call)
    assert CallState(call.state) is CallState.done

    scores = (await session.execute(
        __import__("sqlalchemy").select(Score).where(Score.call_id == call.id)
    )).scalars().all()
    assert len(scores) == 1
    sc = scores[0]
    assert sc.total > 0
    items = {it["item_id"]: it for it in sc.items}
    assert items["greeting"]["evidence"], "evidence обязателен у выполненного пункта"
    # возражение детектировано и отработано агентом
    assert call.objections and call.objections[0].type == "existing_supplier"
    assert call.objections[0].response_status == "handled_success"
