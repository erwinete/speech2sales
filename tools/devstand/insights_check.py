"""Верификация A+B на стенде: кластеры возражений + риск контактов."""

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"


async def main() -> None:
    from sqlalchemy import select

    from polylog.db import make_engine, make_sessionmaker
    from polylog.embeddings import EmbeddingBackend
    from polylog.graph.service import get_default_org
    from polylog.insights.clustering import cluster_items
    from polylog.models.calls import Call, Objection
    from polylog.risk import risk_for_contact

    engine = make_engine(DB)
    sm = make_sessionmaker(engine)

    # A: кластеры возражений
    async with sm() as s:
        org = await get_default_org(s)
        rows = (
            (
                await s.execute(
                    select(Objection.span_text, Objection.type)
                    .join(Call, Call.id == Objection.call_id)
                    .where(Call.org_id == org.id)
                )
            )
            .all()
        )
    print(f"возражений: {len(rows)}")
    if rows:
        emb = EmbeddingBackend()
        vectors = emb.embed([t for t, _ in rows])
        items = [
            {"vector": v, "text": t, "type": ty}
            for v, (t, ty) in zip(vectors, rows, strict=True)
        ]
        clusters = cluster_items(items, threshold=0.82)
        print(f"кластеров: {len(clusters)}")
        for c in clusters[:4]:
            d = c.as_dict()
            print(f"  [{d['size']} шт, {d['dominant_type']}] например: «{d['quotes'][0][:70]}»")

    # B: риск по контактам
    async with sm() as s:
        org = await get_default_org(s)
        from polylog.models.calls import Call

        contact_ids = (
            (
                await s.execute(
                    select(Call.contact_id)
                    .where(Call.org_id == org.id, Call.contact_id.is_not(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        for cid in contact_ids[:4]:
            r = await risk_for_contact(s, org.id, cid)
            if r:
                top = r["factors"][0]["description"]
                print(f"контакт {str(cid)[:8]}: риск {r['score']} ({r['band']}) — {top}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
