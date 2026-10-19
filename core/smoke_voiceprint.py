"""Смоук voiceprint: channel_embedding на стендовых стерео-файлах (wespeaker).

Проверяем: эмбеддинг извлекается; один и тот же канал даёт cosine 1.0;
разные каналы (агент/клиент одного звонка) дают заметно более низкую близость.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["POLYLOG_VOICEPRINT"] = "1"

from polylog.asr import voiceprint
from polylog.asr.diarize import cosine
from polylog.media.normalize import ensure_ffmpeg_on_path

DUAL = Path(__file__).parent.parent / "data" / "datasets" / "infoabayai" / "dual-channel"


async def main() -> None:
    ensure_ffmpeg_on_path()
    t0 = time.time()
    v03_0 = voiceprint.channel_embedding(DUAL / "call-03.wav", 0)
    v03_1 = voiceprint.channel_embedding(DUAL / "call-03.wav", 1)
    v01_1 = voiceprint.channel_embedding(DUAL / "call-01.wav", 1)
    print(f"модель+эмбеддинги за {time.time() - t0:.1f} c, dim={len(v03_0)}")

    sim_self = cosine(v03_0, v03_0)
    sim_across_ch = cosine(v03_0, v03_1)
    sim_cross_call = cosine(v03_0, v01_1)
    print(f"cos(ch0_03, ch0_03) = {sim_self:.3f}   (ожидаем 1.000)")
    print(f"cos(ch0_03, ch1_03) = {sim_across_ch:.3f}   (агент vs клиент — ожидаем низко)")
    print(f"cos(ch0_03, ch1_01) = {sim_cross_call:.3f}   (агент vs агент другого звонка)")

    assert sim_self >= 0.999
    assert sim_across_ch < 0.8, "разные спикеры одного звонка слишком похожи"
    print("ИТОГ: voiceprint-эмбеддинги работают")


asyncio.run(main())
