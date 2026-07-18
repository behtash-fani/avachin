#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import run_acceptance as acceptance  # noqa: E402


class AcceptanceRunnerTests(unittest.TestCase):
    def make_script(self, root: Path, name: str, body: str) -> Path:
        path = root / name
        path.write_text(body, encoding="utf-8")
        return path

    def make_manifest(self, root: Path, scenarios: list[dict[str, object]]) -> Path:
        path = root / "manifest.json"
        path.write_text(
            json.dumps({"schema_version": 1, "name": "test corpus", "scenarios": scenarios}),
            encoding="utf-8",
        )
        return path

    def test_passing_scenario_writes_json_and_csv_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = self.make_script(root, "passing.py", "print('acceptance ok')\n")
            manifest = self.make_manifest(
                root,
                [{"id": "pass", "title": "Pass", "test_files": [str(script)]}],
            )
            report_dir = root / "reports"
            with mock.patch.object(acceptance, "PROJECT_ROOT", root):
                exit_code = acceptance.main(["--manifest", str(manifest), "--report-dir", str(report_dir)])
            self.assertEqual(exit_code, 0)
            payload = json.loads((report_dir / "acceptance-report.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["summary"]["passed"], 1)
            with (report_dir / "acceptance-report.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["scenario_id"], "pass")
            self.assertEqual(rows[0]["status"], "passed")

    def test_mutating_protected_fixture_fails_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protected = root / "original.mp3"
            protected.write_bytes(b"original")
            script = self.make_script(
                root,
                "mutate.py",
                f"from pathlib import Path\nPath({str(protected)!r}).write_bytes(b'changed')\n",
            )
            spec = acceptance.ScenarioSpec(
                scenario_id="mutation",
                title="Mutation",
                description="",
                category="safety",
                test_files=(str(script),),
                protected_paths=(str(protected),),
            )
            with mock.patch.object(acceptance, "PROJECT_ROOT", root):
                result = acceptance.run_scenario(spec)
            self.assertEqual(result.status, "failed")
            self.assertTrue(result.mutated_paths)

    def test_optional_missing_fixture_is_skipped_unless_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = self.make_script(root, "passing.py", "pass\n")
            spec = acceptance.ScenarioSpec(
                scenario_id="optional",
                title="Optional",
                description="",
                category="audio",
                test_files=(str(script),),
                required_paths=(str(root / "missing.mp3"),),
                optional=True,
            )
            with mock.patch.object(acceptance, "PROJECT_ROOT", root):
                skipped = acceptance.run_scenario(spec)
                failed = acceptance.run_scenario(spec, strict_optional=True)
            self.assertEqual(skipped.status, "skipped")
            self.assertEqual(failed.status, "failed")

    def test_manifest_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = self.make_script(root, "passing.py", "pass\n")
            manifest = self.make_manifest(
                root,
                [
                    {"id": "duplicate", "test_files": [str(script)]},
                    {"id": "duplicate", "test_files": [str(script)]},
                ],
            )
            with self.assertRaisesRegex(ValueError, "duplicate scenario ids"):
                acceptance.load_manifest(manifest)

    def test_unknown_selected_scenario_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = self.make_script(root, "passing.py", "pass\n")
            manifest = self.make_manifest(root, [{"id": "known", "test_files": [str(script)]}])
            with mock.patch.object(acceptance, "PROJECT_ROOT", root):
                exit_code = acceptance.main(
                    ["--manifest", str(manifest), "--report-dir", str(root / "reports"), "--scenario", "missing"]
                )
            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
