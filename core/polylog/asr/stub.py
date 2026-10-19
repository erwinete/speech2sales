"""Детерминированный stub-бэкенд для dev/тестов (без ML-зависимостей).

Поведение:
1. Если рядом с WAV лежит sidecar `<имя>.transcript.json` — используем его
   (список {speaker, start_ms, end_ms, text, conf?}); так dev-стенд и бенчмарк
   подают эталонные/синтетические транскрипты.
2. Иначе — делим длительность на сегменты по 5 с, роли чередуются agent/client.
"""

import json
import logging
import os
from pathlib import Path

from polylog.asr.base import AsrBackendError, Utterance, wav_duration_sec

SEGMENT_SEC = 5.0


class StubAsrBackend:
    id = "stub"

    def transcribe(
        self,
        wav_path: Path,
        channels_map: dict[str, str] | None = None,
        hints: dict | None = None,
    ) -> list[Utterance]:
        if not wav_path.is_file():
            raise AsrBackendError(f"аудио не найдено: {wav_path}")

        # sidecar ищем в двух конвенциях: stem-based (x.transcript.json рядом с x.wav)
        # и name-based (x.wav.transcript.json — так кладёт stage_normalize для 16k-копий)
        candidates = [
            wav_path.with_name(wav_path.stem + ".transcript.json"),
            wav_path.with_name(wav_path.name + ".transcript.json"),
        ]
        sidecar = next((c for c in candidates if c.is_file()), None)
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
        if sidecar is not None:
            try:
                items = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise AsrBackendError(f"sidecar {sidecar.name} не читается: {e}") from e
            return [
                Utterance(
                    speaker=str(it.get("speaker", "unknown")),
                    start_ms=int(it.get("start_ms", 0)),
                    end_ms=int(it.get("end_ms", 0)),
                    text=str(it.get("text", "")),
                    conf=float(it["conf"]) if it.get("conf") is not None else None,
                    raw_text=it.get("text"),
                )
                for it in items
            ]

        duration = wav_duration_sec(wav_path)
        n = max(1, -(-int(duration * 1000) // int(SEGMENT_SEC * 1000)))  # ceil, минимум 1
        roles = [self._role(i, channels_map) for i in range(n)]
        return [
            Utterance(
                speaker=roles[i],
                start_ms=int(i * SEGMENT_SEC * 1000),
                end_ms=int(min((i + 1) * SEGMENT_SEC, duration) * 1000),
                text=f"[stub] сегмент {i + 1}/{n}",
                conf=1.0,
                raw_text=None,
            )
            for i in range(n)
        ]

    @staticmethod
    def _role(i: int, channels_map: dict[str, str] | None) -> str:
        # fallback: чередование ролей (телефонный диалог); real diarization — doc 02 §2.3
        if channels_map and str(i % 2) in channels_map:
            return channels_map[str(i % 2)]
        return "agent" if i % 2 == 0 else "client"
