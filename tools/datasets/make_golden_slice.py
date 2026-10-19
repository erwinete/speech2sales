#!/usr/bin/env python3
"""A. Нарезка эталона WER: 90-сек кусок реального звонка → CSV-таблица для разметки.

Выход в data/datasets/golden/:
    slice-<start>-<end>.wav        — нарезка для прослушивания
    golden-template.csv            — ТАБЛИЦА разметки (Excel/LibreOffice/Google Sheets)

Колонки таблицы:
    file     — имя среза (не трогать)
    seq      — номер реплики в срезе (не трогать)
    speaker  — ЗАПОЛНИТЬ: А (агент) | К (клиент) | Х (неразборчиво/не понять)
    text     — дословный текст реплики (при --prefill уже лежит GigaAM-черновик — править)
    notes    — комментарии (# опечатки черновика, странности)

--prefill: раскладывает GigaAM-гипотезу пореплично (разбивка по паузам) —
разметчик только проставляет А/К/Х и правит текст.

Готовую таблицу сохранить как golden.csv рядом со срезами.
"""

from __future__ import annotations

import argparse
import csv
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "datasets" / "infoabayai" / "single-channel" / "call-0000000.wav"
OUT = ROOT / "data" / "datasets" / "golden"
WINDOW_SEC = 30
TOTAL_SEC = 90

CSV_COLUMNS = ("file", "seq", "speaker", "text", "notes")


def cut_slice(src: Path, s: float, e: float, params, rate: float, dst: Path) -> None:
    if dst.exists():
        return
    with wave.open(str(src), "rb") as f:
        f.setpos(int(s * rate))
        data = f.readframes(int((e - s) * rate))
    with wave.open(str(dst), "wb") as d:
        d.setparams(params)
        d.writeframes(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefill", action="store_true",
                    help="GigaAM-черновик пореплично (требует POLYLOG_MODEL_DIR)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    drafts: dict[str, list[dict[str, str]]] = {}
    if args.prefill:
        from polylog.media.normalize import ensure_ffmpeg_on_path

        ensure_ffmpeg_on_path()
        from polylog.asr import get_backend

        backend = get_backend("gigaam-v3-e2e-rnnt")

        def asr_rows(path: Path) -> list[dict[str, str]]:
            return [
                {"speaker": "", "text": u.text}
                for u in backend.transcribe(path, None)
            ]
    else:
        def asr_rows(path: Path) -> list[dict[str, str]]:  # noqa: ARG001
            return [{"speaker": "", "text": ""}]

    with wave.open(str(SRC), "rb") as w:
        params = w.getparams()
        rate = params.framerate
        duration = params.nframes / rate

    total = min(TOTAL_SEC, duration)
    slices = []
    start = 0.0
    while start < total:
        end = min(start + WINDOW_SEC, total)
        slices.append((start, end))
        start = end

    rows_out: list[dict[str, str]] = []
    for s, e in slices:
        dst = OUT / f"slice-{int(s):03d}-{int(e):03d}.wav"
        cut_slice(SRC, s, e, params, rate, dst)
        print(f"  {dst.name} ({e - s:.0f} c)")
        name = dst.name
        if args.prefill:
            rep = asr_rows(dst)
            drafts[name] = rep
            for seq, r in enumerate(rep):
                rows_out.append({"file": name, "seq": seq, "speaker": r["speaker"],
                                 "text": r["text"], "notes": ""})
        else:
            rows_out.append({"file": name, "seq": 0, "speaker": "", "text": "", "notes": ""})

    csv_path = OUT / "golden-template.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:  # BOM — кириллица в Excel
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows_out)

    (OUT / "README-GOLDEN.md").write_text(
        """# Ручной эталон WER — разметка в таблице (doc 06 §6)

1. Открой `golden-template.csv` в Excel/LibreOffice/Google Sheets
   (если кириллица кракозябрами: импорт с кодировкой UTF-8, разделитель `;`).
2. Прослушай соответствующий `slice-*.wav`.
3. В колонке `speaker` проставь: **А** (агент/продающий), **К** (клиент),
   **Х** (неразборчиво / не понять кто).
4. В колонке `text` правь черновик ДОСЛОВНО: замены слов, числа словами,
   заминки «э-э» — оставляем. Реплики НЕ удалять (удаление портит WER-эталон).
   Лишнюю реплику черновика можно объединить с соседней в одной ячейке.
   Странности — в `notes`.
5. Сохрани как `golden.csv` (тот же формат) и скажи «golden готов».

Что получится: WER(GigaAM, эталон) — приёмка ADR-4 (порог ≤ 15%);
маркеры А/К — истина ролей (закрывает часть S3); правки текста — фидбек ASR.
""",
        encoding="utf-8",
    )
    pre = " + prefill (реплик: %d)" % len(rows_out) if args.prefill else ""
    print(f"эталон: {OUT} — {len(slices)} срезов{pre}")
    print(f"таблица: {csv_path}")


if __name__ == "__main__":
    main()
