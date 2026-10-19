"""Смоук авто-flip на реальных стерео-файлах стенда (GigaAM, GPU/CPU).

Ожидание из role_validation.json: call-01 → auto_flipped, call-02 → auto_flipped,
call-03 → confirmed (агент на ch0).
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from polylog.asr.gigaam import GigaAMBackend
from polylog.media.normalize import ensure_ffmpeg_on_path

DUAL = Path(__file__).parent.parent / "data" / "datasets" / "infoabayai" / "dual-channel"
EXPECT = {"call-01.wav": "auto_flipped", "call-02.wav": "auto_flipped", "call-03.wav": "confirmed"}


async def main() -> None:
    ensure_ffmpeg_on_path()
    t0 = time.time()
    backend = GigaAMBackend()
    print(f"модель загружена за {time.time() - t0:.1f} c: {backend.id}")

    ok = True
    for fname, expected in EXPECT.items():
        path = DUAL / fname
        new_map, status = backend.prepare_channels(path, {"0": "agent", "1": "client"})
        mark = "OK " if status == expected else "FAIL"
        if status != expected:
            ok = False
        print(f"[{mark}] {fname}: status={status} roles={{{new_map.get('0')}, {new_map.get('1')}}}")
    print("ИТОГ:", "все совпали с role_validation.json" if ok else "есть расхождения!")


asyncio.run(main())
