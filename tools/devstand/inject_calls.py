#!/usr/bin/env python3
"""Инжектор звонков для dev-стенда (doc 09 §3).

Берёт аудио из каталога датасета, раскладывает по конвенции FreePBX monitor,
пишет CDR-строки в Postgres (стандартная таблица `cdr`). Детерминированный seed
→ идемпотентные uniqueid → воспроизводимые прогоны (регресс моделей, S6).

Пример:
    python inject_calls.py --batch 20 \
        --dsn postgresql://polylog:polylog@postgres:5432/polylog \
        --monitor-dir /monitor --dataset-dir /datasets/infoabayai/dual

Аудио: файлы *.wav (рекурсивно). Двухканальные — ch0=agent, ch1=client.
Опционально рядом лежит sidecar `<имя>.transcript.json` — stub-ASR подхватит.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover
    print("нужен psycopg: pip install psycopg[binary]", file=sys.stderr)
    sys.exit(2)

# Пул фейковых «компаний» — заодно наполняет граф для Customer 360 (doc 08 §3)
CLIENT_POOL = [
    "+74950000001", "+74950000002", "+79030000003", "+79030000004",
    "+78120000005", "+78120000006", "+79170000007", "+79170000008",
]
AGENTS = ["101", "102", "103", "104"]


def e164_pool(rng: random.Random) -> list[str]:
    return CLIENT_POOL


def build_cdr_row(rng: random.Random, audio_path: Path, rel: Path, seq: int) -> dict:
    external = hashlib.sha1(f"{audio_path.name}:{seq}".encode()).hexdigest()[:12]  # noqa: S324 — не крипто
    direction = "in" if rng.random() < 0.45 else "out"
    agent = rng.choice(AGENTS)
    client = rng.choice(e164_pool(rng))
    src, dst = (client, agent) if direction == "in" else (agent, client)
    recording = f"{rel.parent / (rel.stem + f'-{external}-{direction}.wav')}"

    # реалистичное расписание: будни 10:00–18:00, отступ от «сейчас» назад
    base = datetime.now(timezone.utc).replace(tzinfo=None)
    offset_days = rng.randint(0, 5)
    hour = rng.randint(10, 17)
    minute = rng.randint(0, 59)
    calldate = (base - timedelta(days=offset_days)).replace(
        hour=hour, minute=minute, second=rng.randint(0, 59), microsecond=0
    )

    return {
        "uniqueid": f"ds-{external}",
        "calldate": calldate,
        "src": src,
        "dst": dst,
        "duration": 120,
        "billsec": rng.choice([60, 90, 120, 180, 240]),
        "disposition": "ANSWERED" if rng.random() > 0.2 else "NO ANSWER",
        "recordingfile": str(recording),
        "_src_audio": audio_path,
        "_direction": direction,
    }


def inject_batch(args: argparse.Namespace, rng: random.Random) -> int:
    audio_files = sorted(p for p in Path(args.dataset_dir).rglob("*.wav"))
    if not audio_files:
        print(f"нет *.wav в {args.dataset_dir}", file=sys.stderr)
        return 0

    monitor = Path(args.monitor_dir)
    day_dir = monitor / datetime.now(timezone.utc).strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    inserted = 0
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cdr (
                uniqueid varchar(64) PRIMARY KEY,
                calldate timestamp,
                src varchar(64), dst varchar(64),
                duration int, billsec int,
                disposition varchar(32),
                recordingfile varchar(512)
            )
            """
        )
        conn.commit()
        for seq in range(args.batch):
            audio = rng.choice(audio_files)
            rel = audio.relative_to(args.dataset_dir)
            row = build_cdr_row(rng, audio, rel, seq)
            src_audio = row.pop("_src_audio")

            cur.execute("SELECT 1 FROM cdr WHERE uniqueid = %s", (row["uniqueid"],))
            if cur.fetchone():
                continue  # уже инжектирован (идемпотентность)

            # копия аудио под именем CDR (sidecar-транскрипт переезжает рядом)
            dst_path = day_dir / Path(row["recordingfile"]).name
            if not dst_path.exists():
                shutil.copy2(src_audio, dst_path)
                sidecar = src_audio.with_name(src_audio.stem + ".transcript.json")
                if sidecar.exists():
                    shutil.copy2(sidecar, dst_path.with_name(dst_path.stem + ".transcript.json"))

            cur.execute(
                """INSERT INTO cdr (uniqueid, calldate, src, dst, duration, billsec,
                                    disposition, recordingfile)
                   VALUES (%(uniqueid)s, %(calldate)s, %(src)s, %(dst)s, %(duration)s,
                           %(billsec)s, %(disposition)s, %(recordingfile)s)""",
                row,
            )
            inserted += 1
        conn.commit()
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", required=True, help="postgresql://user:pass@host:5432/db")
    ap.add_argument("--monitor-dir", required=True)
    ap.add_argument("--dataset-dir", required=True)
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--loop", action="store_true", help="инжектировать каждые --interval сек")
    ap.add_argument("--interval", type=float, default=60.0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    if args.loop:
        while True:
            n = inject_batch(args, rng)
            print(f"[{datetime.now(timezone.utc):%H:%M:%S}] инжектировано {n}")
            time.sleep(args.interval)
    else:
        n = inject_batch(args, rng)
        print(f"инжектировано {n} звонков (seed={args.seed})")


if __name__ == "__main__":
    main()
