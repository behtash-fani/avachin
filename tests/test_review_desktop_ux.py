#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import fingerprint_store_v2 as store  # noqa: E402
from tools import review_service  # noqa: E402
from tools.review_queue_state import ResolvedQueueController  # noqa: E402


class ReviewDesktopUXTests(unittest.TestCase):
    def _report(self, root: Path, source: Path) -> Path:
        report = root / "detection-report.json"
        report.write_text(
            json.dumps(
                {
                    "summary": {"total": 1, "reject": 1},
                    "detections": [
                        {
                            "source_path": str(source),
                            "decision": "REJECT",
                            "decision_reason": "identity-is-missing-or-placeholder",
                            "safe_to_apply": False,
                            "artist": "Unknown Artist",
                            "title": "Unknown Artist",
                            "album": "",
                            "confidence": {"overall": 94.62},
                            "evidence": {"provider": "existing-tags"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return report

    def test_human_verified_item_is_hidden_and_non_human_state_reopens_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Unknown Artist.mp3"
            source.write_bytes(b"test")
            report = self._report(root, source)
            db_path = root / "fingerprints.sqlite3"
            controller = ResolvedQueueController(db_path=db_path)

            initial = controller.queue(report)
            self.assertEqual(len(initial["items"]), 1)
            self.assertEqual(initial["resolved_count"], 0)

            conn = review_service.connect(db_path)
            try:
                with conn:
                    recording_id = store.upsert_recording(
                        conn,
                        artist="Moein Z",
                        title="Naareye Chah",
                        source="human-review",
                        confidence=100.0,
                    )
                    store.upsert_audio_file(
                        conn,
                        recording_id=recording_id,
                        audio_sha256="abc123",
                        source_path=str(source.resolve()),
                        duration_seconds=180.0,
                    )
            finally:
                conn.close()

            resolved = controller.queue(report)
            self.assertEqual(resolved["items"], [])
            self.assertEqual(resolved["resolved_count"], 1)
            identity = resolved["resolved_items"][0]["resolved_identity"]
            self.assertEqual(identity["artist"], "Moein Z")
            self.assertEqual(identity["title"], "Naareye Chah")

            conn = review_service.connect(db_path)
            try:
                with conn:
                    conn.execute(
                        "UPDATE recordings SET source = 'auto-library-learning' WHERE id = ?",
                        (recording_id,),
                    )
            finally:
                conn.close()

            reopened = controller.queue(report)
            self.assertEqual(len(reopened["items"]), 1)
            self.assertEqual(reopened["resolved_count"], 0)

    def test_desktop_gui_contract_contains_clipboard_and_manual_pending_feedback(self) -> None:
        source = (PROJECT_ROOT / "tools" / "avachin_review_desktop_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("<Control-v>", source)
        self.assertIn("<Shift-Insert>", source)
        self.assertIn("<Button-3>", source)
        self.assertIn("manual-pending", source)
        self.assertIn("verified_rows_hidden", source)
        self.assertNotIn("--apply", source)
        self.assertNotIn("import sqlite3", source)

    def test_desktop_gui_check_entrypoint(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/avachin_review_desktop_gui.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["clipboard_shortcuts"])
        self.assertTrue(payload["right_click_paste"])
        self.assertTrue(payload["manual_pending_feedback"])
        self.assertTrue(payload["verified_rows_hidden"])
        self.assertTrue(payload["undo_reopens_rows"])
        self.assertFalse(payload["automatic_learning"])

    def test_windows_launcher_keeps_desktop_features_and_never_apply(self) -> None:
        launcher = (PROJECT_ROOT / "scripts" / "windows" / "review_center.bat").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("avachin_review_alias_gui.py", launcher)
        self.assertIn("clipboard paste", launcher)
        self.assertNotIn("--apply", launcher)


if __name__ == "__main__":
    unittest.main()
