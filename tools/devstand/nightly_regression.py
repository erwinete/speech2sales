#!/usr/bin/env python3
"""S6 nightly-регресс (doc 09 §5, §8): фикс-набор аудио → ASR+эмбеддинг → сравнение
с baseline. Деградация = блокер релиза моделей.

Метрики деградации:
  - WER(baseline_text, new_text) > 0.02 — распознавание «поплыло» (веса/окружение);
  - cosine(baseline_vec, new_vec) < 0.98 — сместилось векторное пространство;
  - рост латентности > 2× baseline.

Первый запуск создаёт baseline (exit 0). Повторные — сравнивают (exit 3 при деградации).

Запуск:
    python nightly_regression.py --audio-dir data/datasets/infoabayai/single-channel \
        --backend gigaam-v3-e2e-rnnt --limit-seconds 90
Расписание: Task Scheduler / cron / procrastinate-periodic (M2+).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from polylog.media.normalize import ensure_ffmpeg_on_path  # noqa: E402

ensure_ffmpeg_on_path()

from polylog.asr import get_backend  # noqa: E402
from polylog.datasets.wer import wer  # noqa: E402
from polylog.embeddings import EmbeddingBackend  # noqa: E402


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate() if w.getframerate() else 0.0


def cut(w: Path, seconds: float, dst: Path) -> Path:
    with wave.open(str(w), "rb") as src:
        params = src.getparams()
        dst.write_bytes(b"")
    with wave.open(str(w), "rb") as src, wave.open(str(dst), "wb") as d:
        d.setparams(params)
        d.writeframes(src.readframes(int(min(seconds, params.nframes / params.framerate) * params.framerate)))
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--backend", default="gigaam-v3-e2e-rnnt")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--limit-seconds", type=float, default=90)
    ap.add_argument("--baseline", default=str(ROOT / "data" / "stand-storage" / "regression_baseline.json"))
    ap.add_argument("--wer-threshold", type=float, default=0.02)
    ap.add_argument("--cos-threshold", type=float, default=0.98)
    args = ap.parse_args()

    audio_dir = Path(args.audio_dir)
    wavs = sorted(audio_dir.glob("*.wav"))[: args.limit]
    if not wavs:
        print(f"нет *.wav в {audio_dir}", file=sys.stderr)
        return 1

    baseline_path = Path(args.baseline)
    baseline: dict = (
        json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {}
    )
    baseline_meta = baseline.get("_meta", {})
    model_changed = baseline_meta.get("backend") != args.backend

    tmp = tempfile.TemporaryDirectory()
    asr = get_backend(args.backend)
    emb = EmbeddingBackend()

    entries: dict[str, dict] = {}
    degraded: list[str] = []

    for w in wavs:
        cut_path = cut(w, args.limit_seconds, Path(tmp.name) / w.name)
        t0 = time.perf_counter()
        utts = asr.transcribe(cut_path, {"0": "agent", "1": "client"})
        latency = time.perf_counter() - t0
        text = " ".join(u.text for u in utts)
        vector = emb.embed([text])[0]

        entry = {"text": text, "vector": vector, "latency_s": round(latency, 2)}
        old = baseline.get(w.name)
        if old is None:
            entries[w.name] = entry
            print(f"  + {w.name}: baseline-запись создана ({latency:.1f} c)")
            continue

        # сравнения с baseline
        w_err = wer(old["text"], text) if not model_changed else 0.0
        cos = 1 - sum((a - b) ** 2 for a, b in zip(old["vector"], vector)) / 2  # для L2: cos = 1 - d²/2
        latency_ratio = latency / max(old.get("latency_s", latency), 0.01)

        status = []
        if w_err > args.wer_threshold:
            degraded.append(f"{w.name}: WER(vs baseline)={w_err:.3f}")
            status.append(f"WER {w_err:.3f}!")
        else:
            status.append(f"WER {w_err:.4f}")
        if cos < args.cos_threshold:
            degraded.append(f"{w.name}: vector drift cos={cos:.4f}")
            status.append(f"cos {cos:.4f}!")
        else:
            status.append(f"cos {cos:.4f}")
        if latency_ratio > 2.0:
            degraded.append(f"{w.name}: latency ×{latency_ratio:.1f}")
            status.append(f"lat ×{latency_ratio:.1f}!")

        entries[w.name] = entry
        print(f"  {w.name}: {', '.join(status)}")

    if model_changed:
        print(f"! backend сменился ({baseline_meta.get('backend')} → {args.backend}): "
              f"WER-сравнение пропущено, baseline будет перезаписан")

    entries["_meta"] = {"backend": args.backend, "created": time.strftime("%Y-%m-%d %H:%M")}
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    tmp.cleanup()

    if degraded:
        print("S6 РЕГРЕСС: " + "; ".join(degraded), file=sys.stderr)
        return 3
    print("S6 OK: деградаций нет"
          + (" (baseline создан)" if not baseline else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
