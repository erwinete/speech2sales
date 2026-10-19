import json
from pathlib import Path

# 1. Golden state
d = Path(r"F:\Z\rechevaua analitika\data\datasets\golden")
rep = d / "benchmark-gigaam-v3-e2e-rnnt.json"
if rep.exists():
    b = json.loads(rep.read_text(encoding="utf-8"))
    print("WER corpus:", f"{b['wer_corpus']:.2%}", "| RTF:", b["rtf_avg"], "| эталонов:", b["files_with_reference"])
sidecars = list(d.glob("*.transcript.json"))
print("sidecar-эталонов:", len(sidecars))

rows = list(csv := __import__("csv").DictReader(
    open(d / "golden-template.csv", encoding="utf-8-sig"), delimiter=";"))
marked = [r for r in rows if r.get("speaker", "").strip()]
print("строк разметки:", len(rows), "| с speaker:", len(marked))
print("маркеры:", sorted({r["speaker"].strip() for r in marked}))

# 2. amoCRM keys в .env
env = Path(r"F:\Z\rechevaua analitika\.env").read_text(encoding="utf-8")
amo = [k for k in ("AMOCRM_SUBDOMAIN", "AMOCRM_CLIENT_ID", "AMOCRM_CLIENT_SECRET", "AMOCRM_ACCESS_TOKEN") if k in env]
print("amo ключи в .env:", amo)
