"""A/B: сырой звук vs денойз+loudnorm перед ASR на полевой записи.

Кусок «Калиновского 57» (1:30–3:30 — живой диалог у двери):
вариант A — наша нормализация как есть; B — ffmpeg highpass+afftdn+loudnorm.
Сравниваем текст GigaAM и диаризацию pyannote на обоих вариантах.
Запуск: core> ..\\.venv\\Scripts\\python.exe scripts\\probe_preprocess.py
"""

from __future__ import annotations

import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

SRC = Path(__file__).parents[1] / "data" / "tmp-probe" / "Калиновского 82к1 Кв57-.16k.wav"
OUT = Path(__file__).parents[1] / "data" / "tmp-probe"
CUT_FROM, CUT_TO = 90, 210  # сек
FILTER = "highpass=f=150,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11"


def cut_wav(src: Path, dst: Path, a: int, b: int) -> None:
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        w.setpos(a * params.framerate)
        data = w.readframes((b - a) * params.framerate)
    with wave.open(str(dst), "wb") as w:
        w.setparams(params)
        w.writeframes(data)


def main() -> None:
    from polylog.asr.gigaam import GigaAMBackend  # до pyannote (ffmpeg-DLL фикс)
    from polylog.media.normalize import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path()
    OUT.mkdir(parents=True, exist_ok=True)
    piece_a = OUT / "ab-a-raw.wav"
    cut_wav(SRC, piece_a, CUT_FROM, CUT_TO)

    piece_b = OUT / "ab-b-denoised.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(piece_a), "-af", FILTER,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(piece_b)],
        check=True,
    )
    print(f"кусок {CUT_FROM}-{CUT_TO} c: A(raw) и B(denoise+loudnorm) готовы")

    backend = GigaAMBackend()

    for name, path in (("A raw", piece_a), ("B denoised", piece_b)):
        t0 = time.time()
        utts = backend._transcribe_stream(path, speaker="x", channel_offset=None)
        text = " ".join(u.text for u in utts)
        print(f"\n--- GigaAM {name} ({time.time() - t0:.0f} c, {len(utts)} реплик) ---")
        print(text[:1200])

    # диаризация на обоих вариантах
    from polylog.asr import diarize

    for name, path in (("A raw", piece_a), ("B denoised", piece_b)):
        t0 = time.time()
        turns = diarize.diarize(path)
        by: dict[str, int] = {}
        for t in turns:
            by[t["speaker"]] = by.get(t["speaker"], 0) + (t["end_ms"] - t["start_ms"])
        print(
            f"\n--- pyannote {name} ({time.time() - t0:.0f} c): спикеров {len(by)}: "
            + ", ".join(f"{k}={v // 1000} c" for k, v in sorted(by.items()))
        )
        print("   первые транзы:", [(t["start_ms"] // 1000, t["speaker"]) for t in turns[:10]])


if __name__ == "__main__":
    main()
