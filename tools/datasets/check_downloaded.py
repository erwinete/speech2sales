"""Проверка скачанных файлов + числа строк датасета."""

import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))
from polylog.datasets import infobayai as I  # noqa: E402

d = Path("data/datasets/infoabayai/single-channel")
print("=== скачанные файлы:")
for f in sorted(d.glob("*.wav")):
    try:
        with wave.open(str(f), "rb") as w:
            ch, rate, frames = w.getnchannels(), w.getframerate(), w.getnframes()
            dur = frames / rate
            print(f"  {f.name}: {f.stat().st_size / 1e6:.1f} МБ, {ch} кан., {rate} Гц, {dur / 60:.1f} мин")
    except wave.Error as e:
        print(f"  {f.name}: НЕ WAV ({e}), {f.stat().st_size / 1e6:.1f} МБ")

print("\n=== число строк датасета (rows length=100, offset 0/3/100):")
for off in (0, 3, 100):
    page = I.get_rows(I.load_token(), I.DATASET_SINGLE, offset=off, length=100)
    n = len(page.get("rows", []))
    print(f"  offset={off}: rows={n}")
    if n and n < 100:
        break

print("\n=== проверка через /size:")
try:
    import httpx

    r = httpx.get(
        "https://datasets-server.huggingface.co/size?dataset="
        "InfoBayAI%2FRussian-Call-Center-Audio-Dataset-Single-Channel",
        headers=I.auth_headers(I.load_token()),
        timeout=30,
    )
    print(json.dumps(r.json(), ensure_ascii=False)[:500])
except Exception as e:  # noqa: BLE001
    print("size endpoint:", e)
