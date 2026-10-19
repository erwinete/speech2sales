#!/usr/bin/env python3
"""A: ингест dual-channel звонков в стенд с канал-ролями из валидации (S3).

python ingest_dual_stereo.py [--backend gigaam-v3-e2e-rnnt]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

ROOT = Path(__file__).resolve().parents[2]
DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"


async def _segments(session, call_id):
    from sqlalchemy import select

    from polylog.models.calls import CallSegment

    return (
        (
            await session.execute(
                select(CallSegment).where(CallSegment.call_id == call_id).order_by(CallSegment.idx)
            )
        )
        .scalars()
        .all()
    )


async def main(backend: str) -> int:
    from polylog.config import Settings
    from polylog.db import init_db, make_engine, make_sessionmaker
    from polylog.graph.service import get_default_org
    from polylog.ingest.base import CallRef
    from polylog.ingest.service import create_call_from_ref
    from polylog.models.enums import CallState
    from polylog.pipeline import process_call
    from polylog.storage import LocalStorage

    d = ROOT / "data" / "datasets" / "infoabayai" / "dual-channel"
    validation = {
        v["file"]: v
        for v in json.loads((d / "role_validation.json").read_text(encoding="utf-8"))
    }

    settings = Settings(
        database_url=DB,
        storage_dir=str(ROOT / "data" / "stand-storage"),
        tmp_dir=str(ROOT / "data" / "tmp"),
        api_token="stand",
        asr_backend=backend,
        inline_process=True,
        _env_file=None,  # type: ignore[call-arg]
    )
    engine = make_engine(DB)
    await init_db(engine)
    sm = make_sessionmaker(engine)
    storage = LocalStorage(settings.storage_dir)

    async with sm() as session:
        org = await get_default_org(session)
        n = 0
        for wav in sorted(d.glob("call-*.wav")):
            val = validation.get(wav.name, {})
            flipped = val.get("flipped", False)
            channels_hint = {"0": "client", "1": "agent"} if flipped else {"0": "agent", "1": "client"}
            ref = CallRef(
                external_id=f"dual-{wav.stem}",
                started_at=datetime.now(UTC),
                direction="inbound",
                phone_from="+79031112233",
                phone_to="101",
                recording_uri=wav.name,
                channels_hint=channels_hint,
                consent_flag=True,
            )
            call = await create_call_from_ref(
                session, org, None, ref, storage, audio=wav.read_bytes(), source="devstand"
            )
            if call is None:
                print(f"  = {wav.name}: уже в базе")
                continue
            t0 = datetime.now(UTC)
            call = await process_call(session, call.id, settings, storage)
            await session.commit()
            segs = await _segments(session, call.id)
            roles = sorted({s.speaker for s in segs})
            print(f"  {wav.name}: state={call.state}, roles={roles}, "
                  f"wall={(datetime.now(UTC) - t0).total_seconds():.0f} c")
            n += 1
    await engine.dispose()
    print(f"ингестировано стерео-звонков: {n}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="gigaam-v3-e2e-rnnt")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.backend)))
