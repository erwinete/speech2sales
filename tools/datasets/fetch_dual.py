#!/usr/bin/env python3
"""Загрузчик dual-channel сэмплов InfoBayAI: SPEAKER_00/01 → стерео звонок.

Dual-репозиторий хранит звонок как два моно-файла (SPEAKER_00.wav + SPEAKER_01.wav).
Собираем в стерео WAV: ch0=SPEAKER_00 (условно агент), ch1=SPEAKER_01 (условно клиент) —
роли проверяются на стенде S3 (doc 09 §5) и в UI.

Запуск: python fetch_dual.py [--out data/datasets/infoabayai/dual-channel]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

import httpx  # noqa: E402

from polylog.datasets import infobayai as I  # noqa: E402


def list_dir(dataset: str, path: str) -> list[dict]:
    url = f"https://huggingface.co/api/datasets/{dataset}/tree/main"
    if path:
        url += "/" + path
    r = httpx.get(url, headers=I.auth_headers(I.load_token()), timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def download(dataset: str, path: str) -> bytes:
    url = f"https://huggingface.co/datasets/{dataset}/resolve/main/{path}"
    return I.download_audio(url, I.load_token())


def merge_stereo(agent_wav: bytes, client_wav: bytes) -> bytes:
    """Два моно PCM16 → один стерео (выравнивание по короткому)."""

    def read_frames(data: bytes) -> tuple[int, bytearray]:
        with wave.open(io.BytesIO(data), "rb") as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2, "ожидается моно PCM16"
            return w.getframerate(), bytearray(w.readframes(w.getnframes()))

    rate_a, frames_a = read_frames(agent_wav)
    rate_b, frames_b = read_frames(client_wav)
    assert rate_a == rate_b, f"разные частоты: {rate_a} vs {rate_b}"

    n = min(len(frames_a), len(frames_b)) // 2
    out = bytearray()
    for i in range(n):
        a = frames_a[i * 2 : i * 2 + 2]
        b = frames_b[i * 2 : i * 2 + 2]
        out += a + b

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate_a)
        w.writeframes(bytes(out))
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "data" / "datasets" / "infoabayai" / "dual-channel"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_dirs = [
        i["path"] for i in list_dir(I.DATASET_DUAL, "")
        if i.get("type") == "directory"
    ]
    print(f"каталогов-сэмплов: {len(sample_dirs)}")

    manifest = (out_dir / "manifest.jsonl").open("a", encoding="utf-8")
    saved = 0
    try:
        for d in sample_dirs:
            files = list_dir(I.DATASET_DUAL, d)
            by_name = {Path(f["path"]).name: f for f in files if f.get("type") == "file"}
            sp0, sp1 = by_name.get("SPEAKER_00.wav"), by_name.get("SPEAKER_01.wav")
            if not (sp0 and sp1):
                print(f"  ! {d}: нет пары SPEAKER_00/01")
                continue
            fname = f"call-{d.split('-')[-1].strip()}.wav"
            fpath = out_dir / fname
            if fpath.exists():
                print(f"  = {fname} уже есть")
                continue
            merged = merge_stereo(
                download(I.DATASET_DUAL, sp0["path"]),
                download(I.DATASET_DUAL, sp1["path"]),
            )
            fpath.write_bytes(merged)
            manifest.write(json.dumps({
                "file": fname,
                "source": [sp0["path"], sp1["path"]],
                "channels_map": {"0": "agent", "1": "client"},
                "role_map_status": "auto",  # гипотеза SPEAKER_00=агент; проверить S3
                "dataset": I.DATASET_DUAL,
                "license": "CC-BY-4.0",
                "attribution": "InfoBayAI (Hugging Face), CC BY 4.0",
            }, ensure_ascii=False) + "\n")
            saved += 1
            print(f"  + {fname} ({len(merged) / 1e6:.1f} МБ стерео)")
    finally:
        manifest.close()
    print(f"готово: {saved} стерео-звонков в {out_dir}")


if __name__ == "__main__":
    main()
