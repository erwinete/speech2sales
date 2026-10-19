from pathlib import Path

p = Path(r"F:\Z\rechevaua analitika\.env")
t = p.read_text(encoding="utf-8")
if "POLYLOG_DIARIZATION" not in t:
    t += "\nPOLYLOG_DIARIZATION=pyannote\n"
    p.write_text(t, encoding="utf-8")
    print("POLYLOG_DIARIZATION=pyannote добавлен в .env")
else:
    print("уже есть")
