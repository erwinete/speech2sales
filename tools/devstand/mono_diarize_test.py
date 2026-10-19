"""GPU-прогон mono-диаризации: GigaAM + pyannote на 3090. Прогон + замер RTF."""

import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    import asyncio as _a

    _a.set_event_loop_policy(_a.WindowsSelectorEventLoopPolicy())

env_file = Path(__file__).resolve().parents[2] / ".env"
for line in env_file.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())
os.environ.setdefault("HF_HOME", r"F:\Z\polylog-hf")
os.environ.setdefault("POLYLOG_MODEL_DIR", r"F:\Z\polylog-models")
os.environ["POLYLOG_DIARIZATION"] = "pyannote"

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from polylog.media.normalize import ensure_ffmpeg_on_path  # noqa: E402

ensure_ffmpeg_on_path()

import tempfile  # noqa: E402
import wave  # noqa: E402

import torch  # noqa: E402

from polylog.asr import get_backend  # noqa: E402

print("cuda available:", torch.cuda.is_available())

SRC = Path(__file__).resolve().parents[2] / "data" / "datasets" / "infoabayai" / "single-channel" / "call-0000000.wav"
SECONDS = 90

with wave.open(str(SRC), "rb") as w:
    params = w.getparams()
    cut = Path(os.environ["TMP"]) / "mono90.wav"
    with wave.open(str(cut), "wb") as d:
        d.setparams(params)
        d.writeframes(w.readframes(int(min(SECONDS, params.nframes / params.framerate) * params.framerate)))

backend = get_backend("gigaam-v3-e2e-rnnt")
t0 = time.time()
utts = backend.transcribe(cut, None)  # mono → диаризация внутри (GPU)
wall = time.time() - t0

speakers = sorted({u.speaker for u in utts})
print(f"реплик: {len(utts)}, спикеры: {speakers}, wall: {wall:.0f} c (GPU RTF ≈ {wall / SECONDS:.2f})")
for u in utts[:10]:
    print(f"  [{u.speaker}] {u.text[:80]}")
