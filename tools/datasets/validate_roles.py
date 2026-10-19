#!/usr/bin/env python3
"""S3: валидация ролей SPEAKER_00/01 — транскрипция каналов + маркеры агента/клиента.

Выход: data/datasets/infoabayai/dual-channel/role_validation.json
       + обновление manifest.jsonl (role_map_status, agent_channel, evidence).

Запуск: python tools/datasets/validate_roles.py [--seconds 90]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from polylog.asr.gigaam import GigaAMBackend  # noqa: E402
from polylog.media.normalize import ensure_ffmpeg_on_path  # noqa: E402

AGENT_MARKERS = re.compile(
    r"(компан\w+ |меня зовут|представля\w+|предлагаю|чем могу|наш\w* (продукт|сервис|услуг)"
    r"|бесплатн|демонстрац|давайте я покажу|у нас есть|готов\w+ (предложить|рассказать))",
    re.I,
)
CLIENT_MARKERS = re.compile(
    r"(хочу|скажите|сколько|а что|а как|мне нужно|подскажит|спасибо|мы ищем|интересует)",
    re.I,
)


def cut_channel(src: Path, channel: int, seconds: float, dst: Path) -> None:
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        rate, frames = params.framerate, params.nframes
        total = frames / rate
        n = int(min(seconds, total) * rate)
        raw = w.readframes(n)
    bytes_per_sample = params.sampwidth
    bytes_per_frame = bytes_per_sample * params.nchannels
    offset = channel * bytes_per_sample
    mono = bytearray()
    for i in range(offset, len(raw) - bytes_per_sample + 1, bytes_per_frame):
        mono += raw[i : i + bytes_per_sample]
    with wave.open(str(dst), "wb") as d:
        d.setnchannels(1)
        d.setsampwidth(params.sampwidth)
        d.setframerate(rate)
        d.writeframes(bytes(mono))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "datasets" / "infoabayai" / "dual-channel"))
    ap.add_argument("--seconds", type=float, default=90.0)
    args = ap.parse_args()
    ensure_ffmpeg_on_path()

    d = Path(args.dir)
    backend = GigaAMBackend()  # v3_e2e_rnnt

    report = []
    manifest_path = d / "manifest.jsonl"
    manifest = [json.loads(l) for l in manifest_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    with tempfile.TemporaryDirectory(prefix="polylog-roles-") as td:
        for entry in manifest:
            f = d / entry["file"]
            stats = {}
            for ch, role_key in (("0", entry.get("channels_map", {}).get("0", "agent")),
                                 ("1", entry.get("channels_map", {}).get("1", "client"))):
                mono = Path(td) / f"{f.stem}-ch{ch}.wav"
                cut_channel(f, int(ch), args.seconds, mono)
                utts = backend._transcribe_stream(mono, speaker=f"ch{ch}", channel_offset=None)
                text = " ".join(u.text for u in utts)
                speech_sec = sum((u.end_ms - u.start_ms) / 1000 for u in utts)
                stats[role_key] = {
                    "channel": f"ch{ch}",
                    "speech_sec": round(speech_sec, 1),
                    "agent_markers": len(AGENT_MARKERS.findall(text)),
                    "client_markers": len(CLIENT_MARKERS.findall(text)),
                    "first_phrase": (utts[0].text[:90] if utts else "(нет речи)"),
                    "text_head": text[:220],
                }
            # вердикт: агент — канал с бОльшим числом агентских маркеров
            a0, a1 = stats["agent"]["agent_markers"], stats["client"]["agent_markers"]
            verdict = ("SPEAKER_00=agent подтверждён" if a0 >= a1
                       else "ПЕРЕВЕРНУТЬ: агент на ch1 (SPEAKER_01)")
            flipped = a1 > a0
            print(f"--- {entry['file']}: {verdict}")
            for role_key, s in stats.items():
                print(f"    {role_key} ({s['channel']}): речь {s['speech_sec']} c, "
                      f"маркеры агент={s['agent_markers']} клиент={s['client_markers']}")
                print(f"      первые фразы: {s['text_head']}")
            report.append({"file": entry["file"], "verdict": verdict, "flipped": flipped, "stats": stats})

            for m in manifest:
                if m["file"] == entry["file"]:
                    m["role_map_status"] = "flipped" if flipped else "confirmed"
                    m["agent_channel"] = "1" if flipped else "0"
                    m["validation"] = {"agent_markers": [a0, a1], "seconds": args.seconds}

    (d / "role_validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest_path.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in manifest) + "\n", encoding="utf-8"
    )
    print(f"\nотчёт: {d / 'role_validation.json'}; manifest обновлён")


if __name__ == "__main__":
    main()
