#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Structured subprocess operation API for Avachin frontends.

The organizer remains isolated in a child process. Desktop/mobile-facing adapters
receive versioned JSON-compatible events instead of scraping terminal output.
No provider credential is accepted or serialized by this module.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.version import AVACHIN_VERSION  # noqa: E402

EVENT_SCHEMA_VERSION = 1
SUPPORTED_OPERATIONS = {
    "organizer-preview",
    "organizer-apply",
    "bulk-index-preview",
    "bulk-index-apply",
}
PHASE_RE = re.compile(r"^Phase\s+(?P<current>\d+)(?:[a-z])?/(?P<total>\d+):\s*(?P<label>.+)$", re.I)
BRACKET_PROGRESS_RE = re.compile(
    r"^\s*\[(?P<current>\d+)/(?P<total>\d+)\]\s*(?P<message>.*)$"
)
NAMED_PROGRESS_RE = re.compile(
    r"^\s*(?P<label>Metadata scan|Fingerprint index):\s*"
    r"(?P<current>\d+)/(?P<total>\d+)\s*$",
    re.I,
)
REPORT_RE = re.compile(
    r"^\s*(?P<label>Reports|CSV report|JSON summary|Undo manifest|Database backup):\s*"
    r"(?P<path>.+?)\s*$",
    re.I,
)
AUDIO_REPAIR_RE = re.compile(
    r"^\s*\[audio-repair\]\s*(?P<message>.+?)(?::\s*(?P<path>.+))?\s*$",
    re.I,
)
SUMMARY_VALUE_RE = re.compile(
    r"^\s*(?P<label>"
    r"MP3 files|Non-MP3 files|MP3 files scanned|Eligible new fingerprint files|"
    r"Fingerprints indexed|Existing fingerprints repaired|Local segments|Schema version"
    r"):\s*(?P<value>.+?)\s*$",
    re.I,
)
SECRET_MARKERS = (
    "api_token",
    "api key",
    "apikey",
    "client_secret",
    "authorization:",
    "bearer ",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class OperationRequest:
    operation: str
    root: str
    copy_to: str = ""
    offline: bool = False
    workers: int | None = None
    min_confidence: float | None = None
    normalize_persian: bool = False
    id3_version: str = "2.3"
    bulk_limit: int | None = None
    bulk_db: str = ""
    report_dir: str = ""
    progress_every: int = 25
    extra_args: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        return "apply" if self.operation.endswith("-apply") else "preview"

    @property
    def family(self) -> str:
        return "bulk-index" if self.operation.startswith("bulk-index-") else "organizer"

    def normalized(self) -> "OperationRequest":
        operation = str(self.operation or "").strip().casefold()
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError(
                f"unsupported operation {self.operation!r}; "
                f"choose one of {', '.join(sorted(SUPPORTED_OPERATIONS))}"
            )
        root = Path(self.root).expanduser()
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        copy_to = ""
        if self.copy_to:
            copy_target = Path(self.copy_to).expanduser()
            if operation.startswith("bulk-index-"):
                raise ValueError("copy_to is only valid for organizer operations")
            copy_to = str(copy_target.resolve())
        if self.id3_version not in {"2.3", "2.4"}:
            raise ValueError("id3_version must be 2.3 or 2.4")
        workers = None if self.workers is None else max(1, int(self.workers))
        confidence = (
            None
            if self.min_confidence is None
            else max(0.0, min(100.0, float(self.min_confidence)))
        )
        limit = None if self.bulk_limit is None else max(0, int(self.bulk_limit))
        progress = max(1, int(self.progress_every or 25))
        return OperationRequest(
            operation=operation,
            root=str(root.resolve()),
            copy_to=copy_to,
            offline=bool(self.offline),
            workers=workers,
            min_confidence=confidence,
            normalize_persian=bool(self.normalize_persian),
            id3_version=self.id3_version,
            bulk_limit=limit,
            bulk_db=str(Path(self.bulk_db).expanduser().resolve()) if self.bulk_db else "",
            report_dir=(
                str(Path(self.report_dir).expanduser().resolve())
                if self.report_dir
                else ""
            ),
            progress_every=progress,
            extra_args=tuple(str(value) for value in self.extra_args),
        )


@dataclass(frozen=True)
class OperationEvent:
    operation_id: str
    sequence: int
    event_type: str
    operation: str
    mode: str
    timestamp: str = field(default_factory=utc_now)
    schema_version: int = EVENT_SCHEMA_VERSION
    stream: str = ""
    message: str = ""
    phase: str = ""
    current: int | None = None
    total: int | None = None
    path: str = ""
    key: str = ""
    value: Any = None
    status: str = ""
    exit_code: int | None = None
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value not in ("", None)
        }


OperationListener = Callable[[OperationEvent], None]


def build_command(
    request: OperationRequest,
    *,
    python_executable: str | None = None,
) -> list[str]:
    request = request.normalized()
    executable = python_executable or sys.executable
    if request.family == "organizer":
        command = [
            executable,
            "-u",
            str(PROJECT_ROOT / "tools" / "avachin_runtime.py"),
            "--folder",
            request.root,
            "--id3-version",
            request.id3_version,
        ]
        if request.mode == "apply":
            command.append("--apply")
        if request.copy_to:
            command.extend(["--copy-to", request.copy_to])
        if request.offline:
            command.append("--offline")
        if request.workers is not None:
            command.extend(["--workers", str(request.workers)])
        if request.min_confidence is not None:
            command.extend(["--min-confidence", f"{request.min_confidence:g}"])
        if request.normalize_persian:
            command.append("--normalize-persian")
    else:
        command = [
            executable,
            "-u",
            str(PROJECT_ROOT / "tools" / "avachin_bulk_index.py"),
            "--root",
            request.root,
            "--progress-every",
            str(request.progress_every),
        ]
        if request.mode == "apply":
            command.append("--apply")
        if request.bulk_limit is not None:
            command.extend(["--limit", str(request.bulk_limit)])
        if request.bulk_db:
            command.extend(["--db", request.bulk_db])
        if request.report_dir:
            command.extend(["--report-dir", request.report_dir])
    command.extend(request.extra_args)
    return command


def _safe_message(value: str, limit: int = 4000) -> str:
    text = str(value or "").replace("\x00", "")
    lowered = text.casefold()
    if any(marker in lowered for marker in SECRET_MARKERS):
        return "[redacted potentially sensitive child-process output]"
    return text[:limit]


def classify_output_line(
    line: str,
    *,
    stream: str,
    operation_id: str,
    sequence: int,
    request: OperationRequest,
) -> OperationEvent:
    clean = _safe_message(line.rstrip("\r\n"))
    phase_match = PHASE_RE.match(clean)
    if phase_match:
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="phase",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=phase_match.group("label"),
            phase=phase_match.group("label"),
            current=int(phase_match.group("current")),
            total=int(phase_match.group("total")),
        )

    named_match = NAMED_PROGRESS_RE.match(clean)
    if named_match:
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="progress",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            phase=named_match.group("label").casefold().replace(" ", "-"),
            current=int(named_match.group("current")),
            total=int(named_match.group("total")),
        )

    bracket_match = BRACKET_PROGRESS_RE.match(clean)
    if bracket_match:
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="progress",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=bracket_match.group("message"),
            current=int(bracket_match.group("current")),
            total=int(bracket_match.group("total")),
        )

    report_match = REPORT_RE.match(clean)
    if report_match:
        label = report_match.group("label").casefold().replace(" ", "_")
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="artifact",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            key=label,
            path=report_match.group("path").strip(),
        )

    repair_match = AUDIO_REPAIR_RE.match(clean)
    if repair_match:
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="audio-repair",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=repair_match.group("message").strip(),
            path=(repair_match.group("path") or "").strip(),
        )

    summary_match = SUMMARY_VALUE_RE.match(clean)
    if summary_match:
        raw_value = summary_match.group("value").strip()
        parsed_value: Any = raw_value
        try:
            parsed_value = int(raw_value)
        except ValueError:
            pass
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="summary",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            key=summary_match.group("label").casefold().replace(" ", "_"),
            value=parsed_value,
        )

    event_type = "log"
    lowered = clean.casefold()
    if stream == "stderr" or "error" in lowered or "failed" in lowered:
        event_type = "error"
    elif "warning" in lowered or "skipped" in lowered:
        event_type = "warning"
    return OperationEvent(
        operation_id=operation_id,
        sequence=sequence,
        event_type=event_type,
        operation=request.operation,
        mode=request.mode,
        stream=stream,
        message=clean,
    )


class OperationRunner:
    """Run one Avachin operation in an isolated subprocess."""

    def __init__(self, *, popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen):
        self._popen_factory = popen_factory

    @staticmethod
    def _emit(listener: OperationListener | None, event: OperationEvent) -> None:
        if listener is None:
            return
        try:
            listener(event)
        except Exception:
            # A desktop/mobile listener must not be able to break the operation.
            return

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
        try:
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def run(
        self,
        request: OperationRequest,
        *,
        listener: OperationListener | None = None,
        cancel_event: threading.Event | None = None,
        command_override: Sequence[str] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        request = request.normalized()
        operation_id = uuid.uuid4().hex
        started = time.monotonic()
        sequence = 0

        def emit(event_type: str, **kwargs: Any) -> OperationEvent:
            nonlocal sequence
            sequence += 1
            event = OperationEvent(
                operation_id=operation_id,
                sequence=sequence,
                event_type=event_type,
                operation=request.operation,
                mode=request.mode,
                **kwargs,
            )
            self._emit(listener, event)
            return event

        if cancel_event is not None and cancel_event.is_set():
            duration = round(time.monotonic() - started, 3)
            emit(
                "cancelled",
                status="cancelled",
                message="operation cancelled before process start",
                duration_seconds=duration,
            )
            return {
                "operation_id": operation_id,
                "operation": request.operation,
                "status": "cancelled",
                "exit_code": None,
                "duration_seconds": duration,
            }

        command = list(command_override or build_command(request))
        env = dict(os.environ)
        env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
        if environment:
            env.update({str(key): str(value) for key, value in environment.items()})

        creationflags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

        emit(
            "started",
            status="running",
            message=f"{request.operation} started",
            value={
                "version": AVACHIN_VERSION,
                "family": request.family,
                "root": request.root,
            },
        )

        try:
            process = self._popen_factory(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except Exception as exc:
            duration = round(time.monotonic() - started, 3)
            emit(
                "failed",
                status="failed",
                message=f"operation process could not start: {_safe_message(str(exc))}",
                duration_seconds=duration,
            )
            return {
                "operation_id": operation_id,
                "operation": request.operation,
                "status": "failed",
                "exit_code": None,
                "duration_seconds": duration,
            }

        output_queue: queue.Queue[tuple[str, str] | tuple[str, None]] = queue.Queue()

        def read_stream(name: str, stream: Any) -> None:
            try:
                for output_line in iter(stream.readline, ""):
                    output_queue.put((name, output_line))
            finally:
                output_queue.put((name, None))
                try:
                    stream.close()
                except Exception:
                    pass

        readers = [
            threading.Thread(
                target=read_stream,
                args=("stdout", process.stdout),
                name=f"avachin-{operation_id}-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=read_stream,
                args=("stderr", process.stderr),
                name=f"avachin-{operation_id}-stderr",
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        closed_streams: set[str] = set()
        cancelled = False
        while len(closed_streams) < 2 or process.poll() is None:
            if cancel_event is not None and cancel_event.is_set() and not cancelled:
                cancelled = True
                emit(
                    "cancelling",
                    status="cancelling",
                    message="cancellation requested",
                )
                self._terminate(process)
            try:
                stream_name, output_line = output_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if output_line is None:
                closed_streams.add(stream_name)
                continue
            sequence += 1
            parsed = classify_output_line(
                output_line,
                stream=stream_name,
                operation_id=operation_id,
                sequence=sequence,
                request=request,
            )
            self._emit(listener, parsed)

        for reader in readers:
            reader.join(timeout=1)
        exit_code = process.wait()
        duration = round(time.monotonic() - started, 3)
        if cancelled:
            status = "cancelled"
            emit(
                "cancelled",
                status=status,
                exit_code=exit_code,
                message="operation cancelled",
                duration_seconds=duration,
            )
        elif exit_code == 0:
            status = "completed"
            emit(
                "completed",
                status=status,
                exit_code=exit_code,
                message="operation completed",
                duration_seconds=duration,
            )
        else:
            status = "failed"
            emit(
                "failed",
                status=status,
                exit_code=exit_code,
                message=f"operation failed with exit code {exit_code}",
                duration_seconds=duration,
            )
        return {
            "operation_id": operation_id,
            "operation": request.operation,
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": duration,
        }


def _write_jsonl(event: OperationEvent) -> None:
    sys.stdout.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an Avachin operation in an isolated process and emit versioned "
            "JSONL events for desktop/mobile-facing adapters."
        )
    )
    parser.add_argument("operation", choices=sorted(SUPPORTED_OPERATIONS))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--copy-to", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--min-confidence", type=float)
    parser.add_argument("--normalize-persian", action="store_true")
    parser.add_argument("--id3-version", choices=["2.3", "2.4"], default="2.3")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument(
        "--cancel-file",
        type=Path,
        help="Cancel while running when this file appears.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Validate the request and print the child command without running it.",
    )
    return parser


def main() -> int:
    args, extra_args = _parser().parse_known_args()
    request = OperationRequest(
        operation=args.operation,
        root=str(args.root),
        copy_to=str(args.copy_to or ""),
        offline=bool(args.offline),
        workers=args.workers,
        min_confidence=args.min_confidence,
        normalize_persian=bool(args.normalize_persian),
        id3_version=args.id3_version,
        bulk_limit=args.limit,
        bulk_db=str(args.db or ""),
        report_dir=str(args.report_dir or ""),
        progress_every=args.progress_every,
        extra_args=tuple(extra_args),
    ).normalized()

    if args.print_command:
        print(
            json.dumps(
                {
                    "schema_version": EVENT_SCHEMA_VERSION,
                    "operation": request.operation,
                    "command": build_command(request),
                },
                ensure_ascii=False,
            )
        )
        return 0

    cancel_event = threading.Event()
    watcher: threading.Thread | None = None
    if args.cancel_file:
        cancel_path = Path(args.cancel_file)

        def watch_cancel_file() -> None:
            while not cancel_event.wait(0.2):
                if cancel_path.exists():
                    cancel_event.set()
                    return

        watcher = threading.Thread(target=watch_cancel_file, daemon=True)
        watcher.start()

    result = OperationRunner().run(
        request,
        listener=_write_jsonl,
        cancel_event=cancel_event,
    )
    if watcher is not None:
        cancel_event.set()
        watcher.join(timeout=1)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
