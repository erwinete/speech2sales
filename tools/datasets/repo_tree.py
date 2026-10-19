"""Дерево файлов репозитория InfoBayAI (основной объём — файлы, не rows)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from polylog.datasets import infobayai as I  # noqa: E402

import httpx  # noqa: E402


def tree(dataset: str, path: str = "") -> None:
    url = f"https://huggingface.co/api/datasets/{dataset}/tree/main"
    if path:
        url += "/" + path
    r = httpx.get(url, headers=I.auth_headers(I.load_token()), timeout=30)
    print(f"GET {path or '/'} → {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return
    items = r.json()
    dirs = [i for i in items if i.get("type") == "directory"]
    files = [i for i in items if i.get("type") == "file"]
    for d in dirs[:20]:
        print(f"  [DIR] {d['path']}")
    for f in files[:20]:
        size = f.get("size", 0)
        print(f"  {f['path']} ({size / 1e6:.1f} МБ)" if size > 1e6 else f"  {f['path']} ({size} Б)")
    if len(dirs) > 20:
        print(f"  … ещё {len(dirs) - 20} каталогов")
    if len(files) > 20:
        print(f"  … ещё {len(files) - 20} файлов")
    return


if __name__ == "__main__":
    for ds in [I.DATASET_SINGLE, I.DATASET_DUAL]:
        print(f"===== {ds}")
        tree(ds)
        print()
