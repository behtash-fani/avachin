#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import audd_usage_guard as usage  # noqa: E402
import tools.avachin_audd_budget_launcher as runtime  # noqa: E402


class AudDUsageGuardTests(unittest.TestCase):
    def test_atomic_claim_stops_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "usage.sqlite3"
            first = usage.claim_request(db_path, budget_id="test", limit_count=2)
            second = usage.claim_request(db_path, budget_id="test", limit_count=2)
            blocked = usage.claim_request(db_path, budget_id="test", limit_count=2)

            self.assertTrue(first["allowed"])
            self.assertEqual(first["used"], 1)
            self.assertEqual(first["remaining"], 1)
            self.assertTrue(second["allowed"])
            self.assertEqual(second["used"], 2)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["used"], 2)
            self.assertEqual(blocked["remaining"], 0)
            self.assertTrue(blocked["exhausted"])

    def test_budget_ids_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "usage.sqlite3"
            usage.claim_request(db_path, budget_id="allowance-a", limit_count=3)
            a = usage.budget_status(db_path, budget_id="allowance-a", limit_count=3)
            b = usage.budget_status(db_path, budget_id="allowance-b", limit_count=3)
            self.assertEqual(a["used"], 1)
            self.assertEqual(b["used"], 0)

    def test_reset_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "usage.sqlite3"
            usage.claim_request(db_path, budget_id="test", limit_count=3)
            with self.assertRaisesRegex(RuntimeError, "reset refused"):
                usage.reset_budget(db_path, budget_id="test", limit_count=3)
            reset = usage.reset_budget(
                db_path,
                budget_id="test",
                limit_count=3,
                confirm="RESET",
            )
            self.assertEqual(reset["used"], 0)
            self.assertEqual(reset["remaining"], 3)

    def test_direct_cli_help_from_project_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/audd_usage_guard.py", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("local AudD request budget", completed.stdout)


class AudDBudgetLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_post = runtime._ORIGINAL_POST
        self.original_settings = dict(runtime._BUDGET_SETTINGS)

    def tearDown(self) -> None:
        runtime._ORIGINAL_POST = self.original_post
        runtime._BUDGET_SETTINGS.clear()
        runtime._BUDGET_SETTINGS.update(self.original_settings)

    def test_only_real_audd_post_consumes_budget_and_token_is_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "usage.sqlite3"
            calls: list[str] = []

            def fake_post(url, *args, **kwargs):
                calls.append(str(url))
                return object()

            runtime._ORIGINAL_POST = fake_post
            runtime._BUDGET_SETTINGS.update(
                {
                    "enabled": True,
                    "limit": 1,
                    "budget_id": "test-budget",
                    "db_path": db_path,
                    "fail_closed": True,
                }
            )

            runtime._guarded_post("https://example.com/api", data={"token": "secret-token"})
            before = usage.budget_status(db_path, budget_id="test-budget", limit_count=1)
            self.assertEqual(before["used"], 0)

            runtime._guarded_post(
                runtime.base_launcher.AUDD_RECOGNIZE_URL,
                data={"api_token": "secret-token"},
                files={"file": ("Unknown.mp3", object(), "audio/mpeg")},
            )
            after = usage.budget_status(db_path, budget_id="test-budget", limit_count=1)
            self.assertEqual(after["used"], 1)
            self.assertEqual(len(calls), 2)

            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                runtime._guarded_post(
                    runtime.base_launcher.AUDD_RECOGNIZE_URL,
                    data={"api_token": "secret-token"},
                    files={"file": ("Another.mp3", object(), "audio/mpeg")},
                )
            self.assertEqual(len(calls), 2)
            self.assertNotIn(b"secret-token", db_path.read_bytes())

    def test_fail_closed_blocks_when_ledger_fails(self) -> None:
        calls: list[str] = []

        def fake_post(url, *args, **kwargs):
            calls.append(str(url))
            return object()

        runtime._ORIGINAL_POST = fake_post
        runtime._BUDGET_SETTINGS.update(
            {
                "enabled": True,
                "limit": 300,
                "budget_id": "test-budget",
                "db_path": Path("unused.sqlite3"),
                "fail_closed": True,
            }
        )

        with mock.patch.object(runtime.usage_guard, "claim_request", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(RuntimeError, "request blocked"):
                runtime._guarded_post(runtime.base_launcher.AUDD_RECOGNIZE_URL)
        self.assertEqual(calls, [])

    def test_disabled_guard_does_not_touch_ledger(self) -> None:
        calls: list[str] = []

        def fake_post(url, *args, **kwargs):
            calls.append(str(url))
            return object()

        runtime._ORIGINAL_POST = fake_post
        runtime._BUDGET_SETTINGS.update({"enabled": False})
        with mock.patch.object(runtime.usage_guard, "claim_request") as claim:
            runtime._guarded_post(runtime.base_launcher.AUDD_RECOGNIZE_URL)
        claim.assert_not_called()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
