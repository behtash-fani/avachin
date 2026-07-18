#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public structured operation API for Avachin frontends.

The subprocess implementation lives in ``tools._avachin_operation_core``.
This facade keeps the public import/CLI path stable while normalizing terminal
summary lines into accurate versioned events for desktop and mobile adapters.
"""

from __future__ import annotations

import re
from typing import Any

from tools import _avachin_operation_core as _core

OperationRequest = _core.OperationRequest
OperationEvent = _core.OperationEvent
OperationListener = _core.OperationListener
OperationRunner = _core.OperationRunner
EVENT_SCHEMA_VERSION = _core.EVENT_SCHEMA_VERSION
SUPPORTED_OPERATIONS = _core.SUPPORTED_OPERATIONS
build_command = _core.build_command
utc_now = _core.utc_now

_ORIGINAL_CLASSIFIER = _core.classify_output_line
_COUNT_SUMMARY_RE = re.compile(
    r"^\s*(?P<label>"
    r"Metadata|MP3 files organized|Sidecar files kept with albums|"
    r"Other files moved|Duplicates separated|Preview items|"
    r"Already organized / unchanged|Skipped|"
    r"Errors safely rolled back / failed|Empty folders removed"
    r"):\s*(?P<value>\d+)\s*$",
    re.IGNORECASE,
)
_METADATA_PROGRESS_RE = re.compile(
    r"^\s*Metadata:\s*(?P<current>\d+)/(?P<total>\d+)\s*$",
    re.IGNORECASE,
)
_NOOP_STATUS_RE = re.compile(
    r"^\s*Artist identities:\s*no unresolved identities;\s*skipped\.\s*$",
    re.IGNORECASE,
)


def _key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")


def classify_output_line(
    line: str,
    *,
    stream: str,
    operation_id: str,
    sequence: int,
    request: OperationRequest,
) -> OperationEvent:
    """Classify one child-process line without treating zero counts as failures."""

    clean = str(line or "").rstrip("\r\n")

    progress = _METADATA_PROGRESS_RE.match(clean)
    if progress:
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="progress",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            phase="metadata",
            current=int(progress.group("current")),
            total=int(progress.group("total")),
        )

    count = _COUNT_SUMMARY_RE.match(clean)
    if count:
        value = int(count.group("value"))
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="summary",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            key=_key(count.group("label")),
            value=value,
            status="ok" if value == 0 else "attention",
        )

    if _NOOP_STATUS_RE.match(clean):
        return OperationEvent(
            operation_id=operation_id,
            sequence=sequence,
            event_type="log",
            operation=request.operation,
            mode=request.mode,
            stream=stream,
            message=clean.strip(),
            status="ok",
        )

    return _ORIGINAL_CLASSIFIER(
        line,
        stream=stream,
        operation_id=operation_id,
        sequence=sequence,
        request=request,
    )


# The internal runner resolves this name from its own module globals.
_core.classify_output_line = classify_output_line


def main() -> int:
    return _core.main()


if __name__ == "__main__":
    raise SystemExit(main())
