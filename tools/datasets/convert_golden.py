#!/usr/bin/env python3
"""Конвертер golden.csv (таблица разметки) → sidecar-эталоны для benchmark_asr.

Нормализация speaker: A→agent, K→client, X/Х→unknown; нераспознанные → unknown
(+warning). Таймкоды реплик распределяются пропорционально длине текста внутри
длительности среза (для WER точность не критична).
"""

from __future__ import annotations

import csv
import json
import re
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "data" / "datasets" / "golden"

_MAP = {"A": "agent", "K": "client", "X": "unknown", "Х": "unknown", "К": "client"}


def norm_speaker(raw: str) -> tuple[str, bool]:
    s = (raw or "").strip().strip("'\"").upper()
    for ch in ("A", "K", "X"):
        if ch in s:
            return _MAP[ch], True
    for ch in ("Х", "К"):
        if ch in s:
            return _MAP[ch], True
    return "unknown", False


def slice_duration(wav: Path) -> float:
    import wave

    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / w.getframerate() if w.getframerate() else 0.0


def main() -> int:
    csv_path = GOLDEN / "golden-template.csv"
    if not csv_path.is_file():
        csv_path = GOLDEN / "golden.csv"
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig"), delimiter=";"))
    warnings: list[str] = []
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        fname = r["file"].strip()
        spk, ok = norm_speaker(r.get("speaker", ""))
        if not ok:
            warnings.append(f"{fname} seq={r.get('seq')}: маркер {r.get('speaker')!r} не распознан → unknown")
        text = (r.get("text") or "").strip()
        if not text or text == "[тишина]":
            continue
        by_file.setdefault(fname, []).append({"speaker": spk, "text": text, "chars": len(text)})

    made = 0
    for fname, reps in by_file.items():
        wav = GOLDEN / fname
        if not wav.is_file():
            warnings.append(f"{fname}: нет wav — пропущен")
            continue
        dur_ms = int(slice_duration(wav) * 1000)
        total_chars = sum(r["chars"] for r in reps) or 1
        side = []
        pos = 0
        for r in reps:
            span = int(dur_ms * r["chars"] / total_chars)
            side.append({
                "speaker": r["speaker"],
                "start_ms": pos,
                "end_ms": min(pos + span, dur_ms),
                "text": r["text"],
            })
            pos += span
        out = GOLDEN / (Path(fname).stem + ".transcript.json")
        out.write_text(json.dumps(side, ensure_ascii=False), encoding="utf-8")
        made += 1

    for w in warnings:
        print("  !", w, file=sys.stderr)
    print(f"sidecar-эталонов создано: {made}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
