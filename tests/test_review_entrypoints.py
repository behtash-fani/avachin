#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReviewEntrypointTests(unittest.TestCase):
    def run_python(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )

    def test_review_cli_help(self) -> None:
        completed = self.run_python("tools/avachin_review.py", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout.casefold()
        self.assertIn("review", output)
        self.assertIn("undo", output)
        self.assertIn("revoke", output)
        self.assertIn("learn", output)

    def test_review_gui_help_does_not_open_window(self) -> None:
        completed = self.run_python("tools/avachin_review_gui.py", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("review center", completed.stdout.casefold())

    def test_review_desktop_gui_help_does_not_open_window(self) -> None:
        completed = self.run_python("tools/avachin_review_desktop_gui.py", "--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("review center", completed.stdout.casefold())

    def test_windows_launcher_uses_review_gui_and_never_apply(self) -> None:
        launcher = (PROJECT_ROOT / "scripts" / "windows" / "review_center.bat").read_text(
            encoding="utf-8"
        )
        lowered = launcher.casefold()
        self.assertIn("tools\\avachin_review_desktop_gui.py", lowered)
        self.assertNotIn("--apply", lowered)
        self.assertIn("suggestions only", lowered)
        self.assertIn("clipboard paste", lowered)
        self.assertIn("no music file will be moved", lowered)

    def test_gui_uses_controller_instead_of_sqlite(self) -> None:
        gui = (PROJECT_ROOT / "tools" / "avachin_review_gui.py").read_text(encoding="utf-8")
        online_gui = (PROJECT_ROOT / "tools" / "avachin_review_online_gui.py").read_text(
            encoding="utf-8"
        )
        desktop_gui = (PROJECT_ROOT / "tools" / "avachin_review_desktop_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ReviewController", gui)
        self.assertIn("OnlineReviewController", online_gui)
        self.assertIn("ResolvedQueueController", desktop_gui)
        self.assertNotIn("import sqlite3", gui)
        self.assertNotIn("import sqlite3", online_gui)
        self.assertNotIn("import sqlite3", desktop_gui)
        for source in (gui, online_gui, desktop_gui):
            self.assertNotIn("organizer-apply", source)
            self.assertNotIn("bulk-index-apply", source)


if __name__ == "__main__":
    unittest.main()
