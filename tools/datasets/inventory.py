#!/usr/bin/env python3
"""Инвентаризация датасета InfoBayAI (doc 06 §1.1 чек-лист) через datasets-server.

Запуск:  python inventory.py [--dataset DATASET_ID] [--token-env HF_TOKEN]
Выход:   печатает структуру (сплиты, колонки, аудио/транскрипт-колонки, сэмплы)
         и сохраняет data/datasets/infoabayai/inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.datasets import infobayai as I  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=I.DATASET_SINGLE)
    ap.add_argument("--token-env", default="HF_TOKEN")
    args = ap.parse_args()

    token = I.load_token(os_token(args.token_env))
    if not token:
        print("HF_TOKEN не найден (env или .env)", file=sys.stderr)
        sys.exit(2)

    print(f"dataset: {args.dataset}")
    splits = I.get_splits(token, args.dataset)
    print("splits:", json.dumps(splits.get("splits", [])[:6], ensure_ascii=False))

    rows = I.get_rows(token, args.dataset, offset=0, length=2)
    all_rows = rows.get("rows", [])
    if not all_rows:
        print("rows пусты — проверить конфиг/сплит")
        sys.exit(1)

    first = all_rows[0]["row"]
    print("\nколонки первой строки:")
    for k, v in first.items():
        t = type(v).__name__
        preview = ""
        if isinstance(v, str):
            preview = v[:80]
        elif isinstance(v, dict):
            preview = f"dict keys={list(v.keys())[:6]}"
        elif isinstance(v, (int, float)):
            preview = str(v)
        print(f"  {k}: {t} {preview}")

    url, path, blob = I.extract_audio(first)
    text, text_col = I.extract_transcript(first)
    audio_src_preview = (url or "")[:90] + "…" if url else None
    print(f"\naudio column: url={audio_src_preview}, path={path!r}, bytes={'да' if blob else 'нет'}")
    print(f"transcript column: {text_col!r} → {text[:120] if text else 'НЕ НАЙДЕН'}")

    out_dir = Path(__file__).resolve().parents[2] / "data" / "datasets" / "infoabayai"
    out_dir.mkdir(parents=True, exist_ok=True)
    inventory = {
        "dataset": args.dataset,
        "splits": splits.get("splits", []),
        "columns": {k: type(v).__name__ for k, v in first.items()},
        "audio_column_found": url is not None or blob is not None,
        "audio_path": path,
        "transcript_column": text_col or None,
        "transcript_sample": text,
        "num_rows_sampled": len(all_rows),
    }
    (out_dir / "inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\nсохранено: {out_dir / 'inventory.json'}")


def os_token(name: str) -> str | None:
    import os

    return os.environ.get(name)


if __name__ == "__main__":
    main()
