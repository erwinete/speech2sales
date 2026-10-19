"""Создаёт фикстуру для живого smoke-теста API: wav + sidecar-транскрипт."""

import io
import json
import math
import struct
import wave
from pathlib import Path

out_dir = Path(__file__).resolve().parents[2] / "data" / "smoke"
out_dir.mkdir(parents=True, exist_ok=True)

buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16_000)
    frames = bytearray()
    for i in range(16_000 * 6):
        frames += struct.pack("<h", int(10_000 * math.sin(2 * math.pi * 200 * i / 16_000)))
    w.writeframes(bytes(frames))

(out_dir / "live-call.wav").write_bytes(buf.getvalue())
transcript = [
    {"speaker": "agent", "start_ms": 0, "end_ms": 2500, "text": "Добрый день, компания Ромашка, меня зовут Ирина."},
    {"speaker": "client", "start_ms": 2800, "end_ms": 6000, "text": "Здравствуйте! Сколько стоит ваша подписка?"},
]
(out_dir / "live-call.transcript.json").write_text(
    json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
)
print("OK:", out_dir / "live-call.wav")
