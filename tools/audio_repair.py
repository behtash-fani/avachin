#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-safe temporary audio repair for Avachin analysis pipelines.

The original media file is never renamed, overwritten, retagged, or deleted.
When a decoder/fingerprint tool rejects damaged audio, this module may create a
short-lived re-encoded analysis copy, validate it, and expose that copy through
an isolated context manager. Callers keep processing other files when repair
fails.

The public API is intentionally GUI-friendly:

- ``repair_audio_for_analysis`` yields a structured ``RepairResult``;
- ``install_fingerprint_repair_runtime`` safely wraps a fingerprint module;
- listeners can receive structured started/succeeded/failed events;
- no API key, tag, or original media byte is persisted by this module.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402


DECODE_ERROR_MARKERS = (
    "invalid data found",
    "error reading from the audio source",
    "header missing",
    "invalid frame",
    "failed to decode",
    "decoder error",
    "could not find codec parameters",
    "error submitting packet to decoder",
    "invalid concatenated file",
)


class AudioRepairError(RuntimeError):
    """Base class for a temporary audio-repair failure."""


class AudioRepairUnavailable(AudioRepairError):
    """Raised when repair is enabled but FFmpeg is unavailable."""


class AudioRepairFailed(AudioRepairError):
    """Raised when FFmpeg cannot create or validate a safe analysis copy."""


@dataclass(frozen=True)
class RepairResult:
    source_path: str
    repaired_path: str
    method: str
    original_size_bytes: int
    repaired_size_bytes: int
    temporary: bool
    retained_for_debugging: bool
    elapsed_seconds: float
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairEvent:
    status: str
    source_path: str
    repaired_path: str = ""
    method: str = "ffmpeg-reencode"
    message: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RepairListener = Callable[[RepairEvent], None]
_LISTENERS: list[RepairListener] = []
_LISTENER_LOCK = threading.Lock()


def register_repair_listener(listener: RepairListener) -> None:
    if not callable(listener):
        raise TypeError("repair listener must be callable")
    with _LISTENER_LOCK:
        if listener not in _LISTENERS:
            _LISTENERS.append(listener)


def unregister_repair_listener(listener: RepairListener) -> None:
    with _LISTENER_LOCK:
        if listener in _LISTENERS:
            _LISTENERS.remove(listener)


def _emit(event: RepairEvent) -> None:
    with _LISTENER_LOCK:
        listeners = list(_LISTENERS)
    for listener in listeners:
        try:
            listener(event)
        except Exception:
            # UI/log listeners must never be able to break media processing.
            continue


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() not in {"", "0", "false", "no", "off", "disabled"}


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def load_repair_config() -> dict[str, Any]:
    """Load normal config plus config.local.json without exposing secrets."""
    try:
        loaded = app.load_config(PROJECT_ROOT)
    except Exception:
        loaded = {}
    config = dict(loaded) if isinstance(loaded, dict) else {}

    local_path = PROJECT_ROOT / "config.local.json"
    if local_path.exists():
        try:
            local = json.loads(local_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            local = {}
        if isinstance(local, dict):
            config.update(local)

    env_path = str(os.environ.get("AVACHIN_FFMPEG_PATH") or "").strip()
    if env_path:
        config["audio_repair_ffmpeg_path"] = env_path
    if "AVACHIN_AUDIO_REPAIR_ENABLED" in os.environ:
        config["audio_repair_enabled"] = os.environ["AVACHIN_AUDIO_REPAIR_ENABLED"]
    return config


def find_ffmpeg(config: dict[str, Any] | None = None) -> Path:
    config = dict(config or {})
    configured = str(config.get("audio_repair_ffmpeg_path") or "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            PROJECT_ROOT / "tools" / "ffmpeg.exe",
            PROJECT_ROOT / "tools" / "ffmpeg",
            PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
            PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    discovered = shutil.which("ffmpeg")
    if discovered:
        return Path(discovered).resolve()
    raise AudioRepairUnavailable(
        "FFmpeg was not found. Install FFmpeg, put it in PATH, or set audio_repair_ffmpeg_path."
    )


def should_attempt_repair(error: BaseException | str, config: dict[str, Any] | None = None) -> bool:
    config = dict(config or {})
    if not _bool(config.get("audio_repair_enabled"), True):
        return False
    if not _bool(config.get("audio_repair_only_on_decode_error"), True):
        return True
    message = str(error or "").casefold()
    return any(marker in message for marker in DECODE_ERROR_MARKERS)


def _run_command(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        creationflags=creationflags,
    )


def _message(completed: subprocess.CompletedProcess[str], limit: int = 900) -> str:
    value = completed.stderr or completed.stdout or ""
    return " ".join(str(value).split())[:limit]


@contextmanager
def repair_audio_for_analysis(
    source_path: Path,
    *,
    config: dict[str, Any] | None = None,
) -> Iterator[RepairResult]:
    """Create and validate an isolated MP3 copy suitable for fingerprinting.

    The source path is opened read-only by FFmpeg. The repaired copy lives in a
    unique application-data temporary directory and is deleted automatically,
    unless ``audio_repair_keep_temporary_files`` is explicitly enabled.
    """
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))

    config = dict(config or load_repair_config())
    max_mb = _number(config.get("audio_repair_max_file_mb"), 1024.0, 1.0, 10240.0)
    source_size = source.stat().st_size
    if source_size > int(max_mb * 1024 * 1024):
        raise AudioRepairFailed(
            f"audio file exceeds the configured repair limit ({max_mb:g} MB)"
        )

    timeout_seconds = int(
        _number(config.get("audio_repair_timeout_seconds"), 300.0, 10.0, 3600.0)
    )
    quality = int(_number(config.get("audio_repair_mp3_quality"), 2.0, 0.0, 9.0))
    keep_temp = _bool(config.get("audio_repair_keep_temporary_files"), False)
    ffmpeg = find_ffmpeg(config)

    temp_root_value = str(config.get("audio_repair_temp_dir") or "").strip()
    temp_root = (
        Path(temp_root_value).expanduser()
        if temp_root_value
        else app.app_data_dir() / "audio_repair_tmp"
    )
    temp_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="repair_", dir=str(temp_root))).resolve()
    repaired = work_dir / "repaired.mp3"
    started = time.monotonic()
    _emit(RepairEvent(status="started", source_path=str(source)))

    try:
        command = [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-err_detect",
            "ignore_err",
            "-fflags",
            "+discardcorrupt",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-map_metadata",
            "0",
            "-c:a",
            "libmp3lame",
            "-q:a",
            str(quality),
            "-id3v2_version",
            "3",
            str(repaired),
        ]
        encoded = _run_command(command, timeout_seconds)
        warning = _message(encoded)
        if encoded.returncode != 0:
            raise AudioRepairFailed(
                "FFmpeg could not create a temporary analysis copy"
                + (f": {warning}" if warning else "")
            )
        if not repaired.is_file() or repaired.stat().st_size <= 0:
            raise AudioRepairFailed("FFmpeg returned success but produced no repaired audio")
        if repaired.resolve() == source:
            raise AudioRepairFailed("repair output unexpectedly resolved to the original file")

        validation = _run_command(
            [
                str(ffmpeg),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(repaired),
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            timeout_seconds,
        )
        validation_message = _message(validation)
        if validation.returncode != 0 or validation_message:
            raise AudioRepairFailed(
                "temporary analysis copy failed decode validation"
                + (f": {validation_message}" if validation_message else "")
            )

        elapsed = time.monotonic() - started
        result = RepairResult(
            source_path=str(source),
            repaired_path=str(repaired),
            method="ffmpeg-reencode",
            original_size_bytes=source_size,
            repaired_size_bytes=repaired.stat().st_size,
            temporary=True,
            retained_for_debugging=keep_temp,
            elapsed_seconds=round(elapsed, 3),
            warning=warning,
        )
        _emit(
            RepairEvent(
                status="succeeded",
                source_path=str(source),
                repaired_path=str(repaired),
                message=warning,
                elapsed_seconds=result.elapsed_seconds,
            )
        )
        yield result
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 3)
        _emit(
            RepairEvent(
                status="failed",
                source_path=str(source),
                repaired_path=str(repaired) if repaired.exists() else "",
                message=str(exc),
                elapsed_seconds=elapsed,
            )
        )
        raise
    finally:
        if not keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


def install_fingerprint_repair_runtime(
    fingerprint_module: Any,
    *,
    config_provider: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Wrap ``raw_fingerprint`` once with an isolated repair fallback."""
    current = getattr(fingerprint_module, "raw_fingerprint")
    if getattr(current, "__avachin_audio_repair_runtime__", False):
        return
    original = getattr(current, "__avachin_original_raw_fingerprint__", current)

    def resilient_raw_fingerprint(
        file_path: Path,
        fpcalc_path: Path | None = None,
        timeout: int = 120,
    ) -> tuple[float, list[int]]:
        try:
            return original(file_path, fpcalc_path=fpcalc_path, timeout=timeout)
        except Exception as first_error:
            config = (
                dict(config_provider() or {})
                if config_provider is not None
                else load_repair_config()
            )
            if not should_attempt_repair(first_error, config):
                raise

            try:
                with repair_audio_for_analysis(Path(file_path), config=config) as repaired:
                    result = original(
                        Path(repaired.repaired_path),
                        fpcalc_path=fpcalc_path,
                        timeout=timeout,
                    )
                    if _bool(config.get("audio_repair_log_console"), True):
                        print(
                            "  [audio-repair] temporary analysis copy succeeded: "
                            f"{Path(file_path).name}"
                        )
                    return result
            except Exception as repair_error:
                if _bool(config.get("audio_repair_log_console"), True):
                    print(
                        "  [audio-repair] failed safely: "
                        f"{Path(file_path).name} - {repair_error}"
                    )
                raise RuntimeError(
                    f"{first_error}; automatic temporary audio repair failed: {repair_error}"
                ) from repair_error

    setattr(resilient_raw_fingerprint, "__avachin_original_raw_fingerprint__", original)
    setattr(resilient_raw_fingerprint, "__avachin_audio_repair_runtime__", True)
    fingerprint_module.raw_fingerprint = resilient_raw_fingerprint


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Create a validated temporary analysis copy without modifying the original audio."
    )
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the repaired copy for debugging instead of deleting it on exit.",
    )
    args = parser.parse_args()
    config = load_repair_config()
    if args.keep:
        config["audio_repair_keep_temporary_files"] = True
    try:
        with repair_audio_for_analysis(args.file, config=config) as result:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            if args.keep:
                print(f"Retained repaired copy: {result.repaired_path}")
        return 0
    except Exception as exc:
        print(f"Audio repair failed safely: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
