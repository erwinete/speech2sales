#!/usr/bin/env python3
"""Загрузчик InfoBayAI (doc 06 §4): rows API → аудио + манифест.

Запуск:
    python fetch_infobayai.py --limit 20
    python fetch_infobayai.py --dataset <DUAL_ID> --limit 50 --out dual-channel

Выход (data/datasets/infoabayai/<name>/):
    call-<offset>.wav        — аудио (8/16 кГц, как в источнике)
    manifest.jsonl           — {row, file, audio_src, dataset, license, attribution}
Транскриптов в датасете нет (проверено 2026-10-03) — эталон WER собирается
вручную (doc 06 §6), а этот корпус даёт аудио для пайплайна и псевдоразметки.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.datasets import infobayai as I  # noqa: E402

ATTRIBUTION = "InfoBayAI (Hugging Face), CC BY 4.0 — требуется атрибуция при использовании"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=I.DATASET_SINGLE)
    ap.add_argument("--name", default="single-channel", help="подкаталог в data/datasets/infoabayai/")
    ap.add_argument("--out", default=None, help="переопределить выходной каталог")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args()

    token = I.load_token()
    if not token:
        print("HF_TOKEN не найден (env или .env)", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "data" / "datasets" / "infoabayai" / args.name
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.jsonl"

    saved = skipped = failed = 0
    offset = args.offset
    manifest = manifest_path.open("a", encoding="utf-8")
    try:
        while saved < args.limit:
            page = I.get_rows(token, args.dataset, offset=offset, length=min(50, args.limit - saved + 1))
            rows = page.get("rows", [])
            if not rows:
                break
            for item in rows:
                if saved >= args.limit:
                    break
                row_idx = item.get("row_idx", offset)
                row = item["row"]
                url, path, blob = I.extract_audio(row)
                if not url and blob is None:
                    failed += 1
                    continue
                fname = f"call-{row_idx:07d}.wav"
                fpath = out_dir / fname
                if fpath.exists():
                    skipped += 1
                else:
                    try:
                        data = blob if blob is not None else I.download_audio(url, token)
                    except Exception as e:  # noqa: BLE001 — отдельный файл не роняет батч
                        print(f"  ! row {row_idx}: download failed: {e}", file=sys.stderr)
                        failed += 1
                        continue
                    fpath.write_bytes(data)
                    saved += 1
                manifest.write(json.dumps({
                    "row": row_idx,
                    "file": fname,
                    "audio_src": (url or "")[:160],
                    "dataset": args.dataset,
                    "license": "CC-BY-4.0",
                    "attribution": ATTRIBUTION,
                }, ensure_ascii=False) + "\n")
            offset += len(rows)
            if len(rows) < 50:
                break
    finally:
        manifest.close()

    print(f"скачано: {saved}, пропущено (уже были): {skipped}, ошибок: {failed}")
    print(f"каталог: {out_dir}")
    print(f"манифест: {manifest_path}")


if __name__ == "__main__":
    main()
