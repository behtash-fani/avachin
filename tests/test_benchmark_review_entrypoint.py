#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BenchmarkReviewEntrypointTests(unittest.TestCase):
    def test_help_exposes_quarantine_and_reanalysis(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/benchmark_review.py", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout.casefold()
        self.assertIn("quarantine", output)
        self.assertIn("re-score", output)
        self.assertIn("without regenerating audio", output)

    def test_windows_launcher_uses_review_entrypoint_and_never_apply(self) -> None:
        launcher = (
            PROJECT_ROOT / "scripts" / "windows" / "review_benchmark.bat"
        ).read_text(encoding="utf-8")
        self.assertIn("tools\\benchmark_review.py", launcher)
        self.assertNotIn("run_full_benchmark", launcher)
        self.assertNotIn("--apply", launcher)


if __name__ == "__main__":
    unittest.main()
