"""Глубокий осмотр колонки audio (list) — структура элементов."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from polylog.datasets import infobayai as I  # noqa: E402

rows = I.get_rows(I.load_token(), I.DATASET_SINGLE, offset=0, length=3)
for i, item in enumerate(rows.get("rows", [])[:3]):
    row = item["row"]
    audio = row.get("audio")
    print(f"--- row {i}: audio type={type(audio).__name__}")
    if isinstance(audio, list):
        print(f"    len={len(audio)}")
        for j, el in enumerate(audio[:2]):
            if isinstance(el, dict):
                print(f"    [{j}] dict keys={list(el.keys())}")
                for k, v in el.items():
                    if isinstance(v, str) and (v.startswith("http") or len(v) < 80):
                        print(f"        {k} = {v[:100]}")
                    elif isinstance(v, (int, float)):
                        print(f"        {k} = {v}")
                    else:
                        print(f"        {k}: {type(v).__name__} (len={len(v) if hasattr(v, '__len__') else '?'})")
            else:
                print(f"    [{j}] {type(el).__name__}: {str(el)[:100]}")
    else:
        print("    ", json.dumps(audio, ensure_ascii=False, default=str)[:300])
