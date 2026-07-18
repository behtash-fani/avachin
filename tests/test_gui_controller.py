#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.avachin_operation import OperationEvent  # noqa: E402
from tools.gui_controller import PreviewController  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
        self.request = None
        self.cancel_event = None

    def run(self, request, *, listener=None, cancel_event=None):
        self.request = request
        self.cancel_event = cancel_event
        if listener is not None:
            listener(
                OperationEvent(
                    operation_id="test",
                    sequence=1,
                    event_type="artifact",
                    operation=request.operation,
                    mode=request.mode,
                    key="json_summary",
                    path=str(Path(request.root) / "detection-report.json"),
                )
            )
        return {
            "operation_id": "test",
            "operation": request.operation,
            "status": "completed",
            "exit_code": 0,
            "duration_seconds": 0.01,
        }


class BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, request, *, listener=None, cancel_event=None):
        self.started.set()
        assert cancel_event is not None
        cancel_event.wait(timeout=5)
        return {
            "operation_id": "blocking",
            "operation": request.operation,
            "status": "cancelled",
            "exit_code": 1,
            "duration_seconds": 0.01,
        }


class PreviewControllerTests(unittest.TestCase):
    def test_status_is_loaded_through_public_status_adapter(self) -> None:
        controller = PreviewController(
            status_loader=lambda: {"version": "test", "warnings": []},
            runner=FakeRunner(),
        )
        self.assertEqual(controller.status()["version"], "test")

    def test_preview_uses_only_public_organizer_preview_operation(self) -> None:
        runner = FakeRunner()
        events = []
        completed = []
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = PreviewController(
                status_loader=lambda: {},
                runner=runner,
            )
            controller.start_preview(
                temp_dir,
                offline=True,
                workers=3,
                event_callback=events.append,
                completion_callback=completed.append,
            )
            result = controller.wait(timeout=5)

        self.assertIsNotNone(runner.request)
        self.assertEqual(runner.request.operation, "organizer-preview")
        self.assertEqual(runner.request.mode, "preview")
        self.assertTrue(runner.request.offline)
        self.assertEqual(runner.request.workers, 3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(completed[0]["status"], "completed")
        self.assertEqual(events[0].event_type, "artifact")
        self.assertIn("json_summary", controller.artifacts)
        self.assertNotIn("apply", runner.request.operation)

    def test_running_preview_can_be_cancelled_and_second_start_is_rejected(self) -> None:
        runner = BlockingRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = PreviewController(
                status_loader=lambda: {},
                runner=runner,
            )
            controller.start_preview(temp_dir)
            self.assertTrue(runner.started.wait(timeout=2))
            self.assertTrue(controller.running)
            with self.assertRaises(RuntimeError):
                controller.start_preview(temp_dir)
            self.assertTrue(controller.cancel())
            result = controller.wait(timeout=5)

        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(controller.running)
        self.assertFalse(controller.cancel())

    def test_invalid_folder_is_rejected_before_process_start(self) -> None:
        controller = PreviewController(status_loader=lambda: {}, runner=FakeRunner())
        with self.assertRaises(NotADirectoryError):
            controller.start_preview(PROJECT_ROOT / "does-not-exist")


if __name__ == "__main__":
    unittest.main()
