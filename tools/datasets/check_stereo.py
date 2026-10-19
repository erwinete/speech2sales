"""Проверка стерео-сборок: каналы, частота, RMS по каналам (оба спикера живые?)."""

import wave  # audioop удалён в 3.13 — RMS считаем вручную
from pathlib import Path

d = Path("data/datasets/infoabayai/dual-channel")
for f in sorted(d.glob("*.wav")):
    with wave.open(str(f), "rb") as w:
        ch, rate, frames = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(frames)
    dur = frames / rate
    # RMS по каналам (ручной разбор PCM16 interleaved)
    rms = []
    for c in range(ch):
        vals = []
        for i in range(0, len(raw) // 2, ch):
            s = int.from_bytes(raw[(i + c) * 2 : (i + c) * 2 + 2], "little", signed=True)
            vals.append(s * s)
        rms.append(int((sum(vals) / len(vals)) ** 0.5) if vals else 0)
    print(f"{f.name}: {ch} кан., {rate} Гц, {dur / 60:.1f} мин, RMS ch0={rms[0]}, ch1={rms[1]}")
