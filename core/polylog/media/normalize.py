"""Нормализация аудио (doc 02 §2.1).

Fast path: если вход уже PCM16/16 кГц (1–2 канала) — переиспользуем как есть
(большинство АТС отдают именно такой WAV; stdlib `wave`, без ffmpeg).
Медленный path: ffmpeg → 16 кГц PCM16 (каналы сохраняются).

Карта каналов: конвенция FreePBX — ch0=agent, ch1=client (doc 02 §2.3);
валидация эвристикой приветствия — M2.
"""

import logging
import os
import shutil
import subprocess  # noqa: S404 — фикс. аргументы, без shell
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

TARGET_RATE = 16_000
TARGET_WIDTH = 2  # байта = PCM16

# Portable-ffmpeg на отдельном диске (машина разработки): подключается к PATH
# ВАЖНО: для pyannote/torchcodec нужен SHARED-ffmpeg (avcodec-XX.dll и др.);
# статическая essentials-сборка даст «Could not load libtorchcodec_core4.dll».
PORTABLE_FFMPEG_DIR = Path(os.environ.get(
    "POLYLOG_FFMPEG_DIR",
    r"F:\Z\ffmpeg-shared\ffmpeg-n9.0-latest-win64-gpl-shared-9.0\bin",
))


def ensure_ffmpeg_on_path() -> None:
    """Если ffmpeg не в PATH, но лежит в PORTABLE_FFMPEG_DIR — подключаем (dev-машина)."""
    if shutil.which("ffmpeg") is None and PORTABLE_FFMPEG_DIR.is_dir():
        os.environ["PATH"] = str(PORTABLE_FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")


class MediaError(RuntimeError):
    pass


@dataclass
class NormalizedAudio:
    path: Path
    reused: bool  # True — исходник уже в целевом формате, копия не создавалась
    duration_sec: float
    channels: int
    sample_rate: int
    channels_map: dict[str, str] | None
    dev_resampled: bool = False  # True — линейная интерполяция без ffmpeg (только dev)


def probe_wav(path: Path) -> tuple[int, int, int, int] | None:
    """(channels, rate, frames, sampwidth) или None, если это не читаемый WAV."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnchannels(), w.getframerate(), w.getnframes(), w.getsampwidth()
    except (wave.Error, EOFError, IsADirectoryError, PermissionError, FileNotFoundError):
        return None


def _channels_map(channels: int) -> dict[str, str] | None:
    return {"0": "agent", "1": "client"} if channels == 2 else None


def _convert_with_ffmpeg(src: Path, dst: Path) -> None:
    ensure_ffmpeg_on_path()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaError(
            "вход не PCM16/16кГц WAV, а ffmpeg недоступен — установите ffmpeg "
            "или загрузите 16 кГц PCM WAV"
        )
    cmd = [ffmpeg, "-y", "-i", str(src), "-acodec", "pcm_s16le", "-ar", str(TARGET_RATE), str(dst)]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)  # noqa: S603
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg завершился с ошибкой: {proc.stderr[-400:]!r}")


def _resample_linear_dev(src: Path, dst: Path, target_rate: int = TARGET_RATE) -> None:
    """Dev-fallback: линейная интерполяция 8к→16к без ffmpeg (качество ниже soxr/ffmpeg).

    Только для smoke/dev-стенда; в проде обязателен ffmpeg (или soxr) —
    помечается NormalizedAudio.dev_resampled=True и логируется предупреждением.
    """
    import wave

    with wave.open(str(src), "rb") as w:
        channels, rate, frames, width = (
            w.getnchannels(),
            w.getframerate(),
            w.getnframes(),
            w.getsampwidth(),
        )
        raw = w.readframes(frames)
    if width != TARGET_WIDTH:
        raise MediaError("dev-ресемплер поддерживает только PCM16")

    count = len(raw) // (2 * channels)          # кадры (по всем каналам)
    total_samples = len(raw) // 2               # слоты PCM16 (с учётом интерливинга)
    ratio = target_rate / rate
    out_frames = int(count * ratio)
    samples = [
        int.from_bytes(raw[i * 2 : i * 2 + 2], "little", signed=True)
        for i in range(total_samples)
    ]
    out = bytearray()
    for i in range(out_frames):
        pos = i / ratio
        i0 = int(pos)
        frac = pos - i0
        i1 = min(i0 + 1, count - 1)
        for c in range(channels):
            a = samples[i0 * channels + c]
            b = samples[i1 * channels + c]
            v = int(a + (b - a) * frac)
            out += int(max(-32768, min(32767, v))).to_bytes(2, "little", signed=True)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(TARGET_WIDTH)
        w.setframerate(target_rate)
        w.writeframes(bytes(out))


def normalize_call_audio(source_path: Path, target_path: Path | None = None) -> NormalizedAudio:
    """Идемпотентная стадия normalization.

    target_path — куда писать конвертированную копию (обязателен, если исходник
    не в целевом формате). Fast path копий не создаёт.
    """
    if not source_path.is_file():
        raise MediaError(f"исходный файл не найден: {source_path}")

    ensure_ffmpeg_on_path()

    params = probe_wav(source_path)
    if params is not None:
        channels, rate, frames, width = params
        if width == TARGET_WIDTH and rate == TARGET_RATE and channels in (1, 2):
            return NormalizedAudio(
                path=source_path,
                reused=True,
                duration_sec=round(frames / rate, 3),
                channels=channels,
                sample_rate=rate,
                channels_map=_channels_map(channels),
            )

    if target_path is None:
        raise MediaError("для конвертации не указан target_path")

    params2 = probe_wav(source_path)
    if params2 is None:
        with tempfile.TemporaryDirectory(prefix="polylog-media-") as td:
            tmp_out = Path(td) / "normalized.wav"
            _convert_with_ffmpeg(source_path, tmp_out)
            params2 = probe_wav(tmp_out)
            if params2 is None:
                raise MediaError("после конвертации ffmpeg файл не читается как WAV")
            channels, rate, frames, _ = params2
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # shutil.move, а не Path.replace: tmp на системном диске, target
            # может быть на другом (os.replace между дисками = WinError 17)
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(tmp_out), str(target_path))
        return NormalizedAudio(
            path=target_path,
            reused=False,
            duration_sec=round(frames / rate, 3),
            channels=channels,
            sample_rate=rate,
            channels_map=_channels_map(channels),
        )

    # PCM WAV с иной частотой (телефония 8 кГц): ffmpeg → иначе dev-ресемплер
    channels, rate, frames, width = params2
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        _convert_with_ffmpeg(source_path, target_path)
        dev_resampled = False
    else:
        logging.getLogger("polylog.media").warning(
            "ffmpeg недоступен: дев-ресемплер (линейная интерполяция) — качество понижено"
        )
        _resample_linear_dev(source_path, target_path)
        dev_resampled = True
    params3 = probe_wav(target_path)
    if params3 is None:
        raise MediaError("после ресемплинга файл не читается как WAV")
    channels, rate, frames, _ = params3
    return NormalizedAudio(
        path=target_path,
        reused=False,
        duration_sec=round(frames / rate, 3),
        channels=channels,
        sample_rate=rate,
        channels_map=_channels_map(channels),
        dev_resampled=dev_resampled,
    )
