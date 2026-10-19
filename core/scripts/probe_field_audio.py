"""Проба полевых записей (плохое качество, mono, телефон): полный конвейер.

Для каждого файла: нормализация (16 кГц mono PCM) → pyannote-диаризация
(сырые спикеры + речь по каждому) → GigaAM c ролями (транскрипт с таймингами).
Запуск: core> ..\\.venv\\Scripts\\python.exe scripts\\probe_field_audio.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault("POLYLOG_DIARIZATION", "pyannote")

FILES = [
    r"C:\Users\user\Downloads\Telegram Desktop\Калиновского 82к1 Кв57-.m4a",
    r"C:\Users\user\Downloads\Telegram Desktop\Игуменский тракт 18 40+.m4a",
]
OUT_DIR = Path(__file__).parents[1] / "data" / "tmp-probe"


def fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


def main() -> None:
    # gigaam импортируем ДО pyannote-Pipeline: его импорт подключает
    # ffmpeg-DLL, без которых torchcodec-декодер pyannote на Windows падает
    from polylog.asr.gigaam import GigaAMBackend
    from polylog.media.normalize import ensure_ffmpeg_on_path, normalize_call_audio

    ensure_ffmpeg_on_path()

    from polylog.asr import diarize

    assert diarize.available(), "нужен POLYLOG_DIARIZATION=pyannote и HF_TOKEN в .env"
    backend = GigaAMBackend()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for src in FILES:
        src_path = Path(src)
        print("=" * 90)
        print(f"ФАЙЛ: {src_path.name}")
        if not src_path.is_file():
            print("  !! файл не найден, пропуск")
            continue
        dst = OUT_DIR / (src_path.stem + ".16k.wav")
        t0 = time.time()
        try:
            norm = normalize_call_audio(src_path, dst)
        except Exception as e:  # noqa: BLE001
            print(f"  !! нормализация не удалась: {e}")
            continue
        print(
            f"  нормализация: {norm.duration_sec:.0f} c, "
            f"каналов {norm.channels} → mono, {norm.sample_rate} Гц "
            f"(заняла {time.time() - t0:.1f} c)"
        )

        # 1) сырая диаризация: сколько спикеров выделил pyannote
        t0 = time.time()
        turns = diarize.diarize(dst)
        by_speaker: dict[str, int] = {}
        for t in turns:
            by_speaker[t["speaker"]] = by_speaker.get(t["speaker"], 0) + (t["end_ms"] - t["start_ms"])
        print(
            f"  ДИАРИЗАЦИЯ: транзов {len(turns)}, спикеров {len(by_speaker)} "
            f"({time.time() - t0:.1f} c): "
            + ", ".join(f"{k} = {v / 1000:.0f} c речи" for k, v in sorted(by_speaker.items()))
        )
        if not turns:
            print("  pyannote не нашёл речи — дальше транскрибировать нечего")
            continue

        # 2) транскрибация с ролями (mono → путь через диаризацию)
        t0 = time.time()
        utts = backend.transcribe(dst, None)
        words = {"agent": 0, "client": 0}
        for u in utts:
            words[u.speaker] = words.get(u.speaker, 0) + len(u.text.split())
        print(
            f"  ТРАНСКРИПТ: реплик {len(utts)} ({time.time() - t0:.1f} c): "
            f"агент {words.get('agent', 0)} слов / клиент {words.get('client', 0)} слов"
        )
        limit = 45
        for u in utts[:limit]:
            print(f"    [{fmt_ms(u.start_ms)}-{fmt_ms(u.end_ms)}] {u.speaker:6s}: {u.text}")
        if len(utts) > limit:
            print(f"    … и ещё {len(utts) - limit} реплик")


if __name__ == "__main__":
    main()
