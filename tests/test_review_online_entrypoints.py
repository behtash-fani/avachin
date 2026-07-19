#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.version import AVACHIN_VERSION  # noqa: E402


class ReviewOnlineEntrypointTests(unittest.TestCase):
    def test_windows_launcher_uses_online_review_gui(self) -> None:
        content = (PROJECT_ROOT / "scripts" / "windows" / "review_center.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn("avachin_review_online_gui.py", content)
        self.assertIn("suggestions only", content.casefold())
        self.assertNotIn("--apply", content.casefold())

    def test_gui_exposes_online_suggestions_but_not_direct_learning(self) -> None:
        content = (PROJECT_ROOT / "tools" / "avachin_review_online_gui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Identify selected online", content)
        self.assertIn("Identify all real items online", content)
        self.assertIn("Apply verified identity", content)
        self.assertNotIn("learn_file(", content)
        self.assertNotIn("sqlite3", content)

    def test_resolver_has_benchmark_and_no_auto_learn_guards(self) -> None:
        content = (PROJECT_ROOT / "tools" / "review_online.py").read_text(encoding="utf-8")
        self.assertIn("is_benchmark_sample", content)
        self.assertIn('"database_changed": False', content)
        self.assertIn('"learned": False', content)
        self.assertIn("_ORIGINAL_IDENTIFY_BY_FINGERPRINT", content)
        self.assertIn("_identify_by_audd", content)
        self.assertNotIn("learn_file(", content)

    def test_check_mode_is_headless_and_reports_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "avachin_review_online_gui.py"), "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["version"], AVACHIN_VERSION)
        self.assertTrue(payload["online_suggestions_only"])
        self.assertFalse(payload["automatic_learning"])

    def test_public_version_is_12_12(self) -> None:
        self.assertEqual(AVACHIN_VERSION, "12.12")


if __name__ == "__main__":
    unittest.main()
