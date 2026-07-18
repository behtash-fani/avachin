#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_operation as operation  # noqa: E402


class OperationApiTests(unittest.TestCase):
    def request(self, root: Path, name: str = "organizer-preview") -> operation.OperationRequest:
        return operation.OperationRequest(operation=name, root=str(root))

    def test_builds_canonical_organizer_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = operation.OperationRequest(
                operation="organizer-apply",
                root=temp_dir,
                offline=True,
                workers=3,
                min_confidence=90,
                normalize_persian=True,
                id3_version="2.4",
            )
            command = operation.build_command(request, python_executable="python")
            joined = " ".join(command)
            self.assertIn("tools/avachin_runtime.py", joined.replace("\\", "/"))
            self.assertIn("--folder", command)
            self.assertIn("--apply", command)
            self.assertIn("--offline", command)
            self.assertIn("--workers", command)
            self.assertIn("--normalize-persian", command)

    def test_builds_canonical_bulk_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Path(temp_dir) / "test.sqlite3"
            request = operation.OperationRequest(
                operation="bulk-index-apply",
                root=temp_dir,
                bulk_limit=5,
                bulk_db=str(db),
                progress_every=2,
            )
            command = operation.build_command(request, python_executable="python")
            joined = " ".join(command)
            self.assertIn("tools/avachin_bulk_index.py", joined.replace("\\", "/"))
            self.assertIn("--apply", command)
            self.assertIn("--limit", command)
            self.assertIn("--db", command)

    def test_rejects_missing_root(self) -> None:
        request = operation.OperationRequest(
            operation="organizer-preview",
            root="this-path-does-not-exist",
        )
        with self.assertRaises(NotADirectoryError):
            request.normalized()

    def test_parses_phase_progress_artifact_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = self.request(Path(temp_dir))
            samples = [
                ("Phase 2/4: identifying tracks...", "phase"),
                ("  [3/10] Song.mp3 -> Song / Artist [local 99%]", "progress"),
                ("  Metadata scan: 25/100", "progress"),
                ("CSV report: C:\\Reports\\report.csv", "artifact"),
                ("Fingerprints indexed: 12", "summary"),
            ]
            for index, (line, expected) in enumerate(samples, start=1):
                event = operation.classify_output_line(
                    line,
                    stream="stdout",
                    operation_id="op",
                    sequence=index,
                    request=request,
                )
                self.assertEqual(event.event_type, expected, line)

    def test_sensitive_child_output_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = self.request(Path(temp_dir))
            event = operation.classify_output_line(
                "Authorization: Bearer private-value",
                stream="stderr",
                operation_id="op",
                sequence=1,
                request=request,
            )
            self.assertNotIn("private-value", event.message)
            self.assertIn("redacted", event.message)

    def test_runs_child_and_emits_json_compatible_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            request = self.request(Path(temp_dir))
            script = (
                "print('Phase 1/4: reading local metadata...');"
                "print('  [1/1] track.mp3 -> Song / Artist [local 99%]');"
                "print('CSV report: C:/Reports/report.csv')"
            )
            events: list[operation.OperationEvent] = []
            result = operation.OperationRunner().run(
                request,
                listener=events.append,
                command_override=[sys.executable, "-u", "-c", script],
            )
            self.assertEqual(result["status"], "completed")
            types = [event.event_type for event in events]
            self.assertIn("started", types)
            self.assertIn("phase", types)
            self.assertIn("progress", types)
            self.assertIn("artifact", types)
            self.assertEqual(types[-1], "completed")
            json.dumps([event.to_dict() for event in events])

    def test_nonzero_child_exit_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[operation.OperationEvent] = []
            result = operation.OperationRunner().run(
                self.request(Path(temp_dir)),
                listener=events.append,
                command_override=[
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; print('broken', file=sys.stderr); sys.exit(7)",
                ],
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["exit_code"], 7)
            self.assertEqual(events[-1].event_type, "failed")

    def test_listener_failure_cannot_break_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            def broken_listener(event: operation.OperationEvent) -> None:
                raise RuntimeError("UI listener crashed")

            result = operation.OperationRunner().run(
                self.request(Path(temp_dir)),
                listener=broken_listener,
                command_override=[sys.executable, "-u", "-c", "print('ok')"],
            )
            self.assertEqual(result["status"], "completed")

    def test_process_start_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events: list[operation.OperationEvent] = []

            def fail_popen(*args: object, **kwargs: object) -> object:
                raise OSError("cannot start process")

            result = operation.OperationRunner(popen_factory=fail_popen).run(
                self.request(Path(temp_dir)),
                listener=events.append,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["exit_code"])
            self.assertEqual(events[-1].event_type, "failed")

    def test_pre_cancelled_operation_does_not_start_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cancel_event = threading.Event()
            cancel_event.set()
            fake_popen = mock.Mock()
            events: list[operation.OperationEvent] = []
            result = operation.OperationRunner(popen_factory=fake_popen).run(
                self.request(Path(temp_dir)),
                listener=events.append,
                cancel_event=cancel_event,
            )
            self.assertEqual(result["status"], "cancelled")
            fake_popen.assert_not_called()
            self.assertEqual(events[-1].event_type, "cancelled")


if __name__ == "__main__":
    unittest.main()
