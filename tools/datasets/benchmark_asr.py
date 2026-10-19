#!/usr/bin/env python3
"""S5 бенчмарк ASR (doc 06 §6, doc 09 §5): бэкенд → WER/RTF по каталогу аудио.

Два режима:
  - sidecar-эталоны (`<имя>.transcript.json` рядом с аудио) → WER + RTF (S5 приёмка);
  - без эталонов → RTF + сохранение ASR-вывода в sidecars (псевдотранскрипты
    для dev-стенда и NLI-конвейера, doc 07 §5 сценарий B).

Запуск:
    python benchmark_asr.py --audio-dir data/datasets/infoabayai/single-channel --backend stub
    python benchmark_asr.py --audio-dir data/datasets/infoabayai/single-channel --backend gigaam-v3-rnnt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from polylog.media.normalize import ensure_ffmpeg_on_path  # noqa: E402

ensure_ffmpeg_on_path()

from polylog.asr import get_backend  # noqa: E402
from polylog.datasets.wer import wer_detail  # noqa: E402


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate() if w.getframerate() else 0.0


def load_reference(path: Path) -> str | None:
    sidecar = path.with_name(path.stem + ".transcript.json")
    if not sidecar.is_file():
        return None
    items = json.loads(sidecar.read_text(encoding="utf-8"))
    return " ".join(str(i.get("text", "")) for i in items if i.get("text"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--backend", default="stub")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--out", default=None, help="json-отчёт (по умолчанию рядом с audio-dir)")
    ap.add_argument("--save-pseudo", action="store_true",
                    help="сохранить вывод ASR как sidecar (псевдотранскрипты)")
    ap.add_argument("--limit-seconds", type=int, default=None,
                    help="обрезать каждое аудио до первых N секунд (быстрый прогон)")
    args = ap.parse_args()

    audio_dir = Path(args.audio_dir)
    wavs = sorted(audio_dir.glob("*.wav"))[: args.limit]
    if not wavs:
        print(f"нет *.wav в {audio_dir}", file=sys.stderr)
        sys.exit(1)

    import tempfile

    work_dir = audio_dir
    if args.limit_seconds:
        tmpdir = tempfile.mkdtemp(prefix="polylog-bench-")
        for w in wavs:
            with wave.open(str(w), "rb") as src:
                params = src.getparams()
                cut = Path(tmpdir) / w.name
                with wave.open(str(cut), "wb") as dst:
                    dst.setparams(params)
                    dst.writeframes(
                        src.readframes(int(min(args.limit_seconds, params.nframes / params.framerate) * params.framerate))
                    )
            wavs[wavs.index(w)] = cut
        work_dir = Path(tmpdir)

    backend = get_backend(args.backend)
    rows = []
    total_ref_words = total_err = total_audio = 0.0
    total_time = 0.0
    with_ref = 0

    for wav in wavs:
        dur = wav_duration(wav)
        t0 = time.perf_counter()
        try:
            utterances = backend.transcribe(wav, {"0": "agent", "1": "client"})
        except Exception as e:  # noqa: BLE001 — бэкенд недоступен на этой машине
            print(f"  ! {wav.name}: {e}", file=sys.stderr)
            break
        elapsed = time.perf_counter() - t0
        hyp = " ".join(u.text for u in utterances)
        total_audio += dur
        total_time += elapsed

        ref = load_reference(wav)
        row = {"file": wav.name, "duration_sec": round(dur, 1), "rtf": round(elapsed / dur, 4) if dur else None}

        if ref:
            d = wer_detail(ref, hyp)
            total_ref_words += d["ref_words"]
            total_err += round(d["wer"] * d["ref_words"])
            with_ref += 1
            row["wer"] = round(d["wer"], 4)
            row["details"] = {k: d[k] for k in ("sub", "del", "ins")}
        elif args.save_pseudo and not args.limit_seconds:
            sidecar = (audio_dir / wav.name).with_name(wav.stem + ".transcript.json")
            sidecar.write_text(
                json.dumps(
                    [{"speaker": u.speaker, "start_ms": u.start_ms, "end_ms": u.end_ms, "text": u.text}
                     for u in utterances],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            row["pseudo_saved"] = True
        rows.append(row)

    report = {
        "backend": args.backend,
        "files": len(rows),
        "audio_minutes": round(total_audio / 60, 1),
        "rtf_avg": round(total_time / total_audio, 4) if total_audio else None,
        "wer_corpus": round(total_err / total_ref_words, 4) if total_ref_words else None,
        "files_with_reference": with_ref,
        "rows": rows,
    }
    out = Path(args.out) if args.out else audio_dir / f"benchmark-{args.backend}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"бэкенд: {args.backend} | файлов: {len(rows)} | аудио: {report['audio_minutes']} мин")
    print(f"RTF avg: {report['rtf_avg']}")
    if report["wer_corpus"] is not None:
        print(f"WER corpus: {report['wer_corpus']:.2%} (эталонов: {with_ref})")
    else:
        print("WER: эталоны отсутствуют — режим псевдотранскриптов (--save-pseudo)")
    print(f"отчёт: {out}")


if __name__ == "__main__":
    main()
