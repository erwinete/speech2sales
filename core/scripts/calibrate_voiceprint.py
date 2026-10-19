"""Калибровка порога voiceprint на golden-эталоне (DoD М3 §2.1).

Грунт-труф — сам sidecar (интервалы agent/client): эмбеддинги wespeaker
считаются по интервалам эталона, пары «одна роль» vs «разные роли» дают
распределения косинусов → сетка порогов → лучший accuracy.
Порог не зависит от качества диаризации — только от голосов в данных.

Запуск: core> ..\\.venv\\Scripts\\python.exe scripts\\calibrate_voiceprint.py
Требует HF_TOKEN (как диаризация)."""

from __future__ import annotations

import json
import os
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault("POLYLOG_VOICEPRINT", "1")

from pyannote.audio import Model
from pyannote.core import Segment  # noqa: F401 (контракт)

from polylog.asr.diarize import _token, cosine
from polylog.media.normalize import ensure_ffmpeg_on_path

GOLDEN = Path(__file__).parents[2] / "data" / "datasets" / "golden"
MIN_IV_MS = 1200  # интервалы короче — шум (1-2 слова), не годятся на enrollment


def load_pcm(path: Path):
    """WAV (PCM16) → torch-тензор [1, samples] float32, 16 кГц — без torchcodec.
    8 кГц телефонные записи апсемплируются линейно (спектр ≤4 кГц сохраняется,
    а wespeaker обучен на 16 кГц — как в нормализованном контуре пайплайна)."""
    import wave

    import numpy as np
    import torch

    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
    if rate != 16_000:
        n_out = int(round(len(samples) * 16_000 / rate))
        src_idx = np.arange(n_out, dtype=float) * rate / 16_000
        left = np.clip(src_idx.astype(int), 0, len(samples) - 1)
        right = np.clip(left + 1, 0, len(samples) - 1)
        frac = src_idx - left
        samples = (samples[left] * (1 - frac) + samples[right] * frac).astype("float32")
        rate = 16_000
    return torch.from_numpy(samples).unsqueeze(0), rate


def main() -> None:
    ensure_ffmpeg_on_path()
    model = Model.from_pretrained(voiceprint.EMBED_MODEL, use_auth_token=_token())
    model.eval()

    def embed_interval(wav: Path, s_ms: int, e_ms: int) -> list[float] | None:
        """Вектор интервала: режем PCM в numpy (без torchcodec) → модель."""
        import numpy as np
        import torch

        wave_full, rate = load_pcm(wav)
        chunk = wave_full[:, int(s_ms / 1000 * rate) : int(e_ms / 1000 * rate)]
        if chunk.shape[1] < rate // 4:  # <0.25 c — не несёт голоса
            return None
        with torch.no_grad():
            res = model(chunk.unsqueeze(0))  # [batch=1, channels=1, samples]
        arr = np.asarray(res, dtype=float)
        if arr.ndim > 1:
            arr = arr.mean(axis=0)
        return [float(x) for x in arr] or None

    same: list[float] = []
    diff: list[float] = []
    per_file: list[dict] = []

    for wav in sorted(GOLDEN.glob("*.wav")):
        sidecar = wav.with_suffix(".transcript.json")
        if not sidecar.is_file():
            continue
        segments = json.loads(sidecar.read_text(encoding="utf-8"))
        vectors: dict[str, list[list[float]]] = {"agent": [], "client": []}
        for s in segments:
            role = s.get("speaker")
            if role in vectors and s["end_ms"] - s["start_ms"] >= MIN_IV_MS:
                v = embed_interval(wav, s["start_ms"], s["end_ms"])
                if v:
                    vectors[role].append(v)
        n_same = n_diff = 0
        for role in ("agent", "client"):
            for v1, v2 in combinations(vectors[role], 2):
                same.append(cosine(v1, v2))
                n_same += 1
        for v1 in vectors["agent"]:
            for v2 in vectors["client"]:
                diff.append(cosine(v1, v2))
                n_diff += 1
        per_file.append({
            "file": wav.name,
            "agent_iv": len(vectors["agent"]),
            "client_iv": len(vectors["client"]),
            "pairs": {"same": n_same, "diff": n_diff},
        })
        print(f"{wav.name}: интервалов a/k {len(vectors['agent'])}/{len(vectors['client'])}, пар {n_same}/{n_diff}")

    if not same or not diff:
        print("мало данных для калибровки", file=sys.stderr)
        sys.exit(1)

    from polylog.asr.diarize import VOICEPRINT_THRESHOLD

    best = max(
        (
            (sum(1 for x in diff if x < th) + sum(1 for x in same if x >= th))
            / (len(same) + len(diff)),
            th,
        )
        for th in [round(0.30 + 0.02 * i, 2) for i in range(31)]
    )
    report = {
        "model": voiceprint.EMBED_MODEL,
        "files": per_file,
        "same_cosine": {"min": min(same), "max": max(same), "mean": round(sum(same) / len(same), 4)},
        "diff_cosine": {"min": min(diff), "max": max(diff), "mean": round(sum(diff) / len(diff), 4)},
        "best_threshold": best[1],
        "accuracy_at_best": round(best[0], 4),
        "current_default": VOICEPRINT_THRESHOLD,
    }
    out = GOLDEN / "voiceprint_calibration.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {k: report[k] for k in ("same_cosine", "diff_cosine", "best_threshold", "accuracy_at_best")},
        ensure_ascii=False, indent=2,
    ))
    print(f"отчёт: {out}")


if __name__ == "__main__":
    from polylog.asr import voiceprint

    main()
