"""Rescore mono-звонков: GigaAM + pyannote диаризация (аккуратная версия)."""

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

ROOT = Path(__file__).resolve().parents[2]
DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"

os.environ.setdefault("POLYLOG_DIARIZATION", "pyannote")
os.environ.setdefault("POLYLOG_DATABASE_URL", DB)
os.environ.setdefault("POLYLOG_STORAGE_DIR", str(ROOT / "data" / "stand-storage"))
os.environ.setdefault("POLYLOG_MODEL_DIR", r"F:\Z\polylog-models")
os.environ.setdefault("HF_HOME", r"F:\Z\polylog-hf")
os.environ.setdefault("TMP", r"F:\Z\polylog-tmp")
os.environ.setdefault("TEMP", r"F:\Z\polylog-tmp")

from polylog.media.normalize import ensure_ffmpeg_on_path  # noqa: E402

ensure_ffmpeg_on_path()


async def rescore_one(sm, settings, storage, call_id):
    from sqlalchemy import select, update

    from polylog.models.calls import Call, CallSegment
    from polylog.models.enums import CallState
    from polylog.pipeline import process_call

    async with sm() as s:
        await s.execute(
            update(Call).where(Call.id == call_id).values(state=CallState.discovered.value)
        )
        await s.commit()
    async with sm() as s:
        call = await process_call(s, call_id, settings, storage)
        await s.commit()
        segs = (
            (
                await s.execute(
                    select(CallSegment.speaker).where(CallSegment.call_id == call_id)
                )
            )
            .scalars()
            .all()
        )
    return call.state, sorted(set(segs))


async def main(limit: int) -> int:
    from sqlalchemy import select

    from polylog.config import Settings
    from polylog.db import make_engine, make_sessionmaker
    from polylog.models.calls import Call
    from polylog.models.enums import CallState
    from polylog.storage import LocalStorage

    settings = Settings(
        database_url=DB,
        storage_dir=str(ROOT / "data" / "stand-storage"),
        tmp_dir=str(ROOT / "data" / "tmp"),
        api_token="stand",
        asr_backend="gigaam-v3-e2e-rnnt",
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    storage = LocalStorage(settings.storage_dir)

    async with sm() as s:
        rows = (
            (
                await s.execute(
                    select(Call.id)
                    .where(Call.recording_key.is_not(None), Call.state == CallState.done.value)
                    .order_by(Call.started_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()

    ok = 0
    for n, cid in enumerate(rows, 1):
        try:
            state, roles = await rescore_one(sm, settings, storage, cid)
            ok += 1
            print(f"  {n}. {str(cid)[:8]}: {state}, roles={roles}")
        except Exception as e:  # noqa: BLE001
            print(f"  {n}. {str(cid)[:8]}: ERROR {e}")
    print(f"итог: {ok}/{len(rows)}")
    await engine.dispose()
    return 0


LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 18
sys.exit(asyncio.run(main(LIMIT)))
