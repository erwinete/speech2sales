"""Дистанции между тремя уникальными аудио (не дубли) — проверка различимости."""

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

DB = "postgresql+asyncpg://polylog:polylog@localhost:5432/polylog"


async def main() -> None:
    from sqlalchemy import text

    from polylog.db import make_engine, make_sessionmaker

    engine = make_engine(DB)
    sm = make_sessionmaker(engine)
    async with sm() as s:
        # три РАЗНЫХ вектора (по одному на уникальный исходный файл)
        rows = (
            (
                await s.execute(
                    text(
                        """
                        SELECT DISTINCT ON (left(entity_id::text, 8))
                            entity_id, vector::text
                        FROM embeddings WHERE entity_type='call'
                        ORDER BY left(entity_id::text, 8), created_at
                        """
                    )
                )
            )
            .all()
        )
        # у нас 20 звонков из 3 файлов; векторы идентичны внутри файла — берём 3 различных
        seen: dict[str, str] = {}
        for entity_id, vec in rows:
            # fingerprint: первые 40 символов вектора как ключ содержимого
            seen.setdefault(vec[:120], vec)
        vecs = list(seen.values())[:3]
        print(f"уникальных векторов: {len(seen)}")
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                r = (
                    await s.execute(
                        text("SELECT 1 - (CAST(:a AS halfvec) <=> CAST(:b AS halfvec)) AS sim"),
                        {"a": vecs[i], "b": vecs[j]},
                    )
                ).first()
                print(f"  sim(v{i}, v{j}) = {float(r[0]):.4f}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
