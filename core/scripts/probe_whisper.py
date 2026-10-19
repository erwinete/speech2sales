"""A/B: GigaAM vs Whisper-large-v3-turbo на полевой записи (кусок 1:30–3:30).

Запуск: core> ..\\.venv\\Scripts\\python.exe scripts\\probe_whisper.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

PIECE = Path(__file__).parents[1] / "data" / "tmp-probe" / "ab-a-raw.wav"


def main() -> None:
    from polylog.asr.base import get_backend
    from polylog.media.normalize import ensure_ffmpeg_on_path

    ensure_ffmpeg_on_path()
    backend = get_backend("whisper-large-v3-turbo")
    print(f"бэкенд: {backend.id}")
    t0 = time.time()
    utts = backend._transcribe_stream(PIECE, speaker="x")
    text = " ".join(u.text for u in utts)
    print(f"--- Whisper ({time.time() - t0:.0f} c, {len(utts)} куска) ---")
    print(text[:1500])


if __name__ == "__main__":
    main()
