from pathlib import Path

p = Path(r"F:\Z\rechevaua analitika\core\polylog\asr\stub.py")
t = p.read_text(encoding="utf-8")

old = '''        sidecar = next((c for c in candidates if c.is_file()), None)
        if sidecar is not None:'''
new = '''        sidecar = next((c for c in candidates if c.is_file()), None)
        if sidecar is not None and os.environ.get("POLYLOG_DIARIZATION") == "pyannote":
            # mono-диаризация (doc 02 §2.3): pyannote делит на спикеров,
            # метки строк sidecar ([А]/[К] в golden, unknown в псевдо) игнорируются
            try:
                from polylog.asr.diarize import assign_roles, diarize

                turns = diarize(wav_path)
                assign_roles(turns)
                return [
                    Utterance(
                        speaker=turn["speaker"],
                        start_ms=turn["start_ms"],
                        end_ms=turn["end_ms"],
                        text=f"[диариз.] реплика {turn['speaker']}",
                        conf=None,
                    )
                    for turn in turns
                ]
            except Exception as e:  # noqa: BLE001 — нет модели/токена: fallback на sidecar
                logging.getLogger("polylog.asr.stub").warning(
                    "pyannote недоступен (%s) — использую sidecar", e
                )
        if sidecar is not None:'''
assert old in t, "anchor"
t = t.replace(old, new, 1)
if "import os" not in t.split("class StubAsrBackend")[0]:
    t = t.replace("import json\nfrom pathlib import Path", "import json\nimport os\nfrom pathlib import Path", 1)
if "import logging" not in t:
    t = t.replace("import json", "import json\nimport logging", 1)
p.write_text(t, encoding="utf-8")
print("stub diarization support added")
