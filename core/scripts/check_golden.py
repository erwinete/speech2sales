import csv
from pathlib import Path

for name in ["golden.csv", "golden-template.csv"]:
    p = Path(rf"F:\Z\rechevaua analitika\data\datasets\golden\{name}")
    if not p.exists():
        print(name, "— нет")
        continue
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig"), delimiter=";"))
    filled = [r for r in rows if r.get("speaker", "").strip()]
    print(f"{name}: строк {len(rows)}, с speaker: {len(filled)}")
    for r in rows[:12]:
        print("  ", repr(r.get("speaker", ""))[:8], "|", r.get("text", "")[:60])
