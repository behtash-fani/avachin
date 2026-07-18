#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_operation as operation  # noqa: E402


class OperationEventClassificationTests(unittest.TestCase):
    def request(self, root: Path) -> operation.OperationRequest:
        return operation.OperationRequest(operation="organizer-preview", root=str(root))

    def classify(self, root: Path, line: str) -> operation.OperationEvent:
        return operation.classify_output_line(
            line,
            stream="stdout",
            operation_id="test-op",
            sequence=1,
            request=self.request(root),
        )

    def test_zero_skip_count_is_summary_not_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event = self.classify(Path(temp_dir), "Skipped: 0")
            self.assertEqual(event.event_type, "summary")
            self.assertEqual(event.key, "skipped")
            self.assertEqual(event.value, 0)
            self.assertEqual(event.status, "ok")

    def test_zero_error_count_is_summary_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event = self.classify(
                Path(temp_dir),
                "Errors safely rolled back / failed: 0",
            )
            self.assertEqual(event.event_type, "summary")
            self.assertEqual(event.key, "errors_safely_rolled_back_failed")
            self.assertEqual(event.value, 0)
            self.assertEqual(event.status, "ok")

    def test_nonzero_error_count_requests_attention_without_fake_log_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event = self.classify(
                Path(temp_dir),
                "Errors safely rolled back / failed: 2",
            )
            self.assertEqual(event.event_type, "summary")
            self.assertEqual(event.value, 2)
            self.assertEqual(event.status, "attention")

    def test_metadata_progress_is_structured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event = self.classify(Path(temp_dir), "  Metadata: 1/4")
            self.assertEqual(event.event_type, "progress")
            self.assertEqual(event.phase, "metadata")
            self.assertEqual(event.current, 1)
            self.assertEqual(event.total, 4)

    def test_no_unresolved_identity_message_is_normal_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event = self.classify(
                Path(temp_dir),
                "  Artist identities: no unresolved identities; skipped.",
            )
            self.assertEqual(event.event_type, "log")
            self.assertEqual(event.status, "ok")


if __name__ == "__main__":
    unittest.main()
