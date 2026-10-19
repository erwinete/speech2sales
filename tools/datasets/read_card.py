"""Внутри каталогов + README карточки (теперь доступен с токеном)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from polylog.datasets import infobayai as I  # noqa: E402

import httpx  # noqa: E402


def tree(dataset: str, path: str) -> None:
    url = f"https://huggingface.co/api/datasets/{dataset}/tree/main/{path}"
    r = httpx.get(url, headers=I.auth_headers(I.load_token()), timeout=30)
    print(f"--- {dataset} /{path} → {r.status_code}")
    if r.status_code != 200:
        print(r.text[:200])
        return
    items = r.json()
    print(f"    элементов: {len(items)}")
    for i in items[:10]:
        kind = "[DIR]" if i.get("type") == "directory" else "file"
        size = i.get("size", 0)
        size_str = f"{size / 1e6:.1f} МБ" if size > 1e6 else f"{size} Б"
        print(f"    {kind} {i['path']} ({size_str})")
    if len(items) > 10:
        print(f"    … ещё {len(items) - 10}")


def readme(dataset: str) -> None:
    url = f"https://huggingface.co/datasets/{dataset}/raw/main/README.md"
    r = httpx.get(url, headers=I.auth_headers(I.load_token()), timeout=30)
    print(f"===== README {dataset} → {r.status_code}")
    if r.status_code == 200:
        text = r.text
        print(text[:2600])


if __name__ == "__main__":
    tree(I.DATASET_SINGLE, "Russian")
    tree(I.DATASET_DUAL, "Sample - 01")
    print()
    readme(I.DATASET_SINGLE)
