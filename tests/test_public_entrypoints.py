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


class PublicEntrypointTests(unittest.TestCase):
    def run_python(
        self,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )

    def test_canonical_runtime_exposes_public_version(self) -> None:
        completed = self.run_python(
            "-c",
            (
                "import tools.avachin_runtime as runtime; "
                "print(runtime.app.APP_VERSION)"
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip().splitlines()[-1],
            AVACHIN_VERSION,
        )

    def test_canonical_runtime_exposes_detection_contract(self) -> None:
        completed = self.run_python(
            "-c",
            (
                "import tools.avachin_runtime as runtime; "
                "print(runtime.app.DetectionResultContract.__name__); "
                "print(bool(getattr(runtime.app.determine_candidate, "
                "'__avachin_detection_contract__', False)))"
            ),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.strip().splitlines()
        self.assertEqual(lines[-2], "DetectionResult")
        self.assertEqual(lines[-1], "True")

    def test_canonical_organizer_help_runs(self) -> None:
        completed = self.run_python(
            "tools/avachin_runtime.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.casefold())

    def test_canonical_bulk_index_help_runs(self) -> None:
        completed = self.run_python(
            "tools/avachin_bulk_index.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "already-organized mp3 library",
            completed.stdout.casefold(),
        )

    def test_status_help_runs(self) -> None:
        completed = self.run_python(
            "tools/avachin_status.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "secret-free avachin runtime status",
            completed.stdout.casefold(),
        )

    def test_operation_help_runs(self) -> None:
        completed = self.run_python(
            "tools/avachin_operation.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "isolated process",
            completed.stdout.casefold(),
        )
        self.assertIn("jsonl", completed.stdout.casefold())

    def test_acceptance_help_runs(self) -> None:
        completed = self.run_python(
            "tools/run_acceptance.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "acceptance corpus",
            completed.stdout.casefold(),
        )
        self.assertIn("json/csv", completed.stdout.casefold())

    def test_backup_restore_help_runs(self) -> None:
        completed = self.run_python(
            "tools/avachin_backup.py",
            "--help",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "back up or safely restore",
            completed.stdout.casefold(),
        )
        self.assertIn("backup", completed.stdout.casefold())
        self.assertIn("restore", completed.stdout.casefold())

    def test_windows_launchers_use_only_canonical_entrypoints(
        self,
    ) -> None:
        scripts = PROJECT_ROOT / "scripts" / "windows"
        preview = (scripts / "run_preview.bat").read_text(
            encoding="utf-8"
        )
        apply = (scripts / "run_apply.bat").read_text(
            encoding="utf-8"
        )
        bulk_preview = (
            scripts / "preview_local_index.bat"
        ).read_text(encoding="utf-8")
        bulk_apply = (
            scripts / "apply_local_index.bat"
        ).read_text(encoding="utf-8")
        status = (scripts / "status.bat").read_text(
            encoding="utf-8"
        )
        acceptance = (scripts / "run_acceptance.bat").read_text(
            encoding="utf-8"
        )
        backup = (scripts / "backup.bat").read_text(
            encoding="utf-8"
        )
        restore = (scripts / "restore_dry_run.bat").read_text(
            encoding="utf-8"
        )

        self.assertIn("tools\\avachin_runtime.py", preview)
        self.assertIn(
            "tools\\avachin_runtime.py --apply",
            apply,
        )
        self.assertIn(
            "tools\\avachin_bulk_index.py",
            bulk_preview,
        )
        self.assertIn(
            "tools\\avachin_bulk_index.py",
            bulk_apply,
        )
        self.assertIn("tools\\avachin_status.py", status)
        self.assertIn(
            "tools\\run_acceptance.py",
            acceptance,
        )
        self.assertIn(
            "tools\\avachin_backup.py backup",
            backup,
        )
        self.assertIn(
            "tools\\avachin_backup.py restore",
            restore,
        )
        self.assertIn("--dry-run", restore)
        self.assertNotIn("--apply", restore)
        for launcher in (preview, apply, status):
            self.assertIn(
                "from tools.version import AVACHIN_VERSION",
                launcher,
            )
            self.assertIn("v%AVACHIN_VERSION%", launcher)
            self.assertNotIn("v12.2", launcher)

    def test_local_configuration_example_is_valid_json(self) -> None:
        path = PROJECT_ROOT / "config.local.example.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(
            config["local_fingerprint_partial_enabled"]
        )
        self.assertTrue(config["audio_repair_enabled"])
        self.assertTrue(
            config["audd_request_budget_enabled"]
        )

    def test_acceptance_manifest_is_valid_json(self) -> None:
        path = (
            PROJECT_ROOT
            / "tests"
            / "acceptance"
            / "manifest.json"
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        scenario_ids = [
            scenario["id"]
            for scenario in manifest["scenarios"]
        ]
        self.assertEqual(
            len(scenario_ids),
            len(set(scenario_ids)),
        )
        self.assertIn("operation-contract", scenario_ids)
        self.assertIn(
            "audio-repair-no-original-change",
            scenario_ids,
        )
        self.assertIn(
            "backup-restore-sandbox",
            scenario_ids,
        )
        self.assertIn(
            "explainable-detection-contract",
            scenario_ids,
        )


if __name__ == "__main__":
    unittest.main()
