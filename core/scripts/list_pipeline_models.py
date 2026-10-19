"""Скачать конфиг speaker-diarization-3.1 и перечислить ВСЕ модели, на которые он ссылается."""

import re
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

TOKEN = env["HF_TOKEN"]
url = "https://huggingface.co/pyannote/speaker-diarization-3.1/resolve/main/config.yaml"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
cfg = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")

models = sorted(set(re.findall(r"(?:model|embedding|segmentation)[^\n]*?[=:]\s*.*?(pyannote/[\w\-.]+)", cfg)))
if not models:
    models = sorted(set(re.findall(r"(pyannote/[\w\-.]+)", cfg)))

print("config.yaml ссылается на модели:")
for m in models:
    print(" -", m)
