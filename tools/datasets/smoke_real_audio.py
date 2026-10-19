#!/usr/bin/env python3
"""E2E smoke на реальной телефонии InfoBayAI (S1/S3, doc 09): 8 кГц → пайплайн → done.

Запуск из корня:
    python tools/datasets/smoke_real_audio.py                        # single-channel
    python tools/datasets/smoke_real_audio.py --dir dual-channel     # стерео + карта каналов
"""

import sys
import tempfile
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from polylog.config import Settings  # noqa: E402
from polylog.db import init_db, make_engine, make_sessionmaker  # noqa: E402
from polylog.graph.service import get_default_org  # noqa: E402
from polylog.ingest.base import CallRef  # noqa: E402
from polylog.ingest.service import create_call_from_ref  # noqa: E402
from polylog.models.calls import Call, CallSegment  # noqa: E402
from polylog.models.enums import CallState  # noqa: E402
from polylog.pipeline import process_call  # noqa: E402
from polylog.storage import LocalStorage  # noqa: E402

DEFAULT_DIR = ROOT / "data" / "datasets" / "infoabayai" / "single-channel"


def stereo_hint(wav: Path) -> dict[str, str] | None:
    try:
        with wave.open(str(wav), "rb") as w:
            return {"0": "agent", "1": "client"} if w.getnchannels() == 2 else None
    except wave.Error:
        return None


def main() -> None:
    audio_dir = ROOT / "data" / "datasets" / "infoabayai" / (
        sys.argv[sys.argv.index("--dir") + 1] if "--dir" in sys.argv else "single-channel"
    )
    wavs = sorted(audio_dir.glob("*.wav"))
    if not wavs:
        print(f"нет аудио в {audio_dir}: python tools/datasets/fetch_infobayai.py --limit 10")
        sys.exit(1)

    tmp = tempfile.TemporaryDirectory()
    backend = (
        sys.argv[sys.argv.index("--backend") + 1] if "--backend" in sys.argv else "stub"
    )
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp.name}/smoke.db",
        storage_dir=str(Path(tmp.name) / "storage"),
        tmp_dir=str(Path(tmp.name) / "tmp"),
        api_token="smoke",
        asr_backend=backend,
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = make_engine(settings.database_url)
    import asyncio

    asyncio.run(init_db(engine))
    sm = make_sessionmaker(engine)
    storage = LocalStorage(settings.storage_dir)

    async def run_one(wav: Path, idx: int) -> Call:
        async with sm() as session:
            org = await get_default_org(session)
            audio = wav.read_bytes()
            ref = CallRef(
                external_id=f"infoabayai-{wav.stem}-{backend}",
                started_at=datetime.now(timezone.utc),
                direction="inbound",
                phone_from="+7900000000" + str(idx),
                phone_to="101",
                recording_uri=wav.name,
                channels_hint=stereo_hint(wav),
                consent_flag=True,
            )
            call = await create_call_from_ref(session, org, None, ref, storage, audio=audio, source="devstand")
            assert call is not None
            t0 = datetime.now(timezone.utc)
            call = await process_call(session, call.id, settings, storage)
            await session.commit()
            wall = (datetime.now(timezone.utc) - t0).total_seconds()
            from sqlalchemy import func, select

            from polylog.models.calls import Objection, Score

            score = (
                await session.execute(select(Score).where(Score.call_id == call.id).order_by(Score.created_at.desc()))
            ).scalars().first()
            objections = (
                await session.execute(select(Objection).where(Objection.call_id == call.id))
            ).scalars().all()
            n_segments = (
                await session.execute(
                    select(func.count()).select_from(CallSegment).where(CallSegment.call_id == call.id)
                )
            ).scalar_one()
            first_text = call.segments[0].text[:80] if call.segments else "-"
            print(f"  {wav.name}: state={call.state}, {call.duration_sec} c, wall={wall:.1f} c, "
                  f"реплик={n_segments}, скор={score.total if score else None}, "
                  f"возражений={len(objections)}")
            print(f"    первая реплика: {first_text}")
            return call

    async def run_all() -> list[Call]:
        return [await run_one(w, i) for i, w in enumerate(wavs[:2])]

    calls = asyncio.run(run_all())
    asyncio.run(engine.dispose())
    ok = all(CallState(c.state) is CallState.done for c in calls)
    print("S1 smoke:", "PASSED" if ok else "FAILED")
    tmp.cleanup()
    sys.exit(0 if ok else 3)


if __name__ == "__main__":
    main()
