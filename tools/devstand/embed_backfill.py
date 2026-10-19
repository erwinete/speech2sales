#!/usr/bin/env python3
"""Backfill эмбеддингов по done-звонкам стенда (M9): USER2 → pgvector → HNSW-индекс.

Запуск: python embed_backfill.py [--limit 100]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

ROOT = Path(__file__).resolve().parents[2]
DB = __import__("os").environ.get(
    "POLYLOG_DATABASE_URL", "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"
)


async def main(limit: int) -> int:
    from sqlalchemy import select, text

    from polylog.db import make_engine, make_sessionmaker
    from polylog.embeddings import embed_call_text
    from polylog.models.calls import Call, CallSegment

    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    t0 = time.perf_counter()
    n = 0
    async with sm() as session:
        calls = (
            (
                await session.execute(
                    select(Call).where(Call.state == "done").order_by(Call.started_at).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        print(f"done-звонков: {len(calls)}")
        for call in calls:
            segs = (
                (
                    await session.execute(
                        select(CallSegment)
                        .where(CallSegment.call_id == call.id)
                        .order_by(CallSegment.idx)
                    )
                )
                .scalars()
                .all()
            )
            seg_dicts = [
                {"idx": s.idx, "speaker": s.speaker, "start_ms": s.start_ms,
                 "end_ms": s.end_ms, "text": s.text}
                for s in segs
            ]
            if not seg_dicts:
                continue
            vector, model_id = embed_call_text(seg_dicts)
            vec_literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
            await session.execute(
                text(
                    "INSERT INTO embeddings (org_id, entity_type, entity_id, model_id, dim, vector, meta) "
                    "VALUES (:org, 'call', :eid, :mid, :dim, :vec ::halfvec, '{\"kind\":\"call_mean\"}'::jsonb) "
                    "ON CONFLICT (entity_type, entity_id, model_id) DO UPDATE SET vector = EXCLUDED.vector"
                ),
                {"org": call.org_id, "eid": str(call.id), "mid": model_id,
                 "dim": len(vector), "vec": vec_literal},
            )
            n += 1
        # HNSW-индекс после наполнения (быстрее, чем строить на пустой таблице)
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_embeddings_hnsw "
                "ON embeddings USING hnsw (vector halfvec_cosine_ops) WITH (m=16, ef_construction=64)"
            )
        )
        await session.commit()
    wall = time.perf_counter() - t0
    await engine.dispose()
    print(f"эмбеддингов: {n} за {wall:.1f} c ({wall / max(1, n):.2f} c/звонок)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    sys.exit(asyncio.run(main(int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 100)))
