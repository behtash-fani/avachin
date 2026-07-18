#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe Preview-only controller for Avachin desktop frontends.

The controller intentionally contains no recognition or file-management logic.
It consumes the public Status and Operation APIs and never exposes Apply.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from tools.avachin_operation import OperationEvent, OperationRequest, OperationRunner
from tools.avachin_status import collect_status

EventCallback = Callable[[OperationEvent], None]
CompletionCallback = Callable[[dict[str, Any]], None]


class PreviewController:
    """Run one organizer Preview in a worker thread and expose safe cancellation."""

    def __init__(
        self,
        *,
        status_loader: Callable[[], dict[str, Any]] = collect_status,
        runner: OperationRunner | None = None,
    ) -> None:
        self._status_loader = status_loader
        self._runner = runner or OperationRunner()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._artifacts: dict[str, str] = {}
        self._last_result: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        return dict(self._status_loader())

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def artifacts(self) -> dict[str, str]:
        with self._lock:
            return dict(self._artifacts)

    @property
    def last_result(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._last_result) if self._last_result is not None else None

    def start_preview(
        self,
        folder: str | Path,
        *,
        offline: bool = True,
        workers: int | None = None,
        min_confidence: float | None = None,
        normalize_persian: bool = False,
        event_callback: EventCallback | None = None,
        completion_callback: CompletionCallback | None = None,
    ) -> None:
        root = Path(folder).expanduser()
        if not root.is_dir():
            raise NotADirectoryError(str(root))

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a Preview operation is already running")
            self._cancel_event = threading.Event()
            self._artifacts = {}
            self._last_result = None
            request = OperationRequest(
                operation="organizer-preview",
                root=str(root.resolve()),
                offline=bool(offline),
                workers=workers,
                min_confidence=min_confidence,
                normalize_persian=bool(normalize_persian),
            )

            def listener(event: OperationEvent) -> None:
                if event.event_type == "artifact" and event.path:
                    key = event.key or Path(event.path).name.casefold()
                    with self._lock:
                        self._artifacts[key] = event.path
                if event_callback is not None:
                    event_callback(event)

            def worker() -> None:
                try:
                    result = self._runner.run(
                        request,
                        listener=listener,
                        cancel_event=self._cancel_event,
                    )
                except Exception as exc:  # The GUI must survive an adapter failure.
                    result = {
                        "operation": "organizer-preview",
                        "status": "failed",
                        "exit_code": None,
                        "duration_seconds": 0.0,
                        "error": str(exc),
                    }
                with self._lock:
                    self._last_result = dict(result)
                if completion_callback is not None:
                    try:
                        completion_callback(dict(result))
                    except Exception:
                        pass

            self._thread = threading.Thread(
                target=worker,
                name="avachin-gui-preview",
                daemon=True,
            )
            self._thread.start()

    def cancel(self) -> bool:
        with self._lock:
            if not self._thread or not self._thread.is_alive() or self._cancel_event is None:
                return False
            self._cancel_event.set()
            return True

    def wait(self, timeout: float | None = None) -> dict[str, Any] | None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        return self.last_result
