#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_status as status_api  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


class StatusApiTests(unittest.TestCase):
    def test_fingerprint_status_reads_existing_database_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "fingerprints.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
                INSERT INTO schema_meta VALUES ('schema_version', '3', 'now');
                CREATE TABLE recordings (id TEXT);
                CREATE TABLE audio_files (id INTEGER);
                CREATE TABLE fingerprints (id INTEGER);
                CREATE TABLE external_ids (id INTEGER);
                CREATE TABLE fingerprint_segments (id INTEGER);
                INSERT INTO recordings VALUES ('r1'), ('r2');
                INSERT INTO audio_files VALUES (1), (2), (3);
                INSERT INTO fingerprints VALUES (1), (2), (3);
                INSERT INTO external_ids VALUES (1);
                INSERT INTO fingerprint_segments VALUES (1), (2), (3), (4);
                """
            )
            conn.commit()
            conn.close()
            before = db_path.stat().st_mtime_ns

            result = status_api.fingerprint_status(db_path)

            self.assertEqual(result["schema_version"], 3)
            self.assertEqual(result["recordings"], 2)
            self.assertEqual(result["audio_files"], 3)
            self.assertEqual(result["fingerprints"], 3)
            self.assertEqual(result["segments"], 4)
            self.assertEqual(result["error"], "")
            self.assertEqual(db_path.stat().st_mtime_ns, before)

    def test_audd_budget_status_reads_existing_ledger_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "provider_usage.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE audd_budget_state (
                    budget_id TEXT PRIMARY KEY,
                    limit_count INTEGER,
                    used_count INTEGER,
                    created_at TEXT,
                    updated_at TEXT
                );
                INSERT INTO audd_budget_state
                VALUES ('manual-300', 300, 7, 'created', 'updated');
                """
            )
            conn.commit()
            conn.close()
            before = db_path.stat().st_mtime_ns

            result = status_api.audd_budget_status(
                {
                    "audd_request_budget_enabled": True,
                    "audd_request_budget_id": "manual-300",
                    "audd_request_budget_limit": 300,
                },
                db_path,
            )

            self.assertEqual(result["used"], 7)
            self.assertEqual(result["remaining"], 293)
            self.assertFalse(result["exhausted"])
            self.assertEqual(result["error"], "")
            self.assertEqual(db_path.stat().st_mtime_ns, before)

    def test_status_never_serializes_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fingerprint_db = root / "missing-fingerprints.sqlite3"
            audd_db = root / "missing-budget.sqlite3"
            config = {
                "online_providers": {
                    "acoustid": True,
                    "audd": True,
                    "spotify": True,
                },
                "acoustid_api_key": "ACOUSTID-PRIVATE-SECRET",
                "audd_api_token": "AUDD-PRIVATE-SECRET",
                "spotify_client_id": "SPOTIFY-ID-SECRET",
                "spotify_client_secret": "SPOTIFY-PRIVATE-SECRET",
                "audio_repair_enabled": False,
            }

            result = status_api.collect_status(
                project_root=root,
                config_override=config,
                fingerprint_db_path=fingerprint_db,
                audd_db_path=audd_db,
            )
            payload = json.dumps(result, sort_keys=True)

            self.assertNotIn("ACOUSTID-PRIVATE-SECRET", payload)
            self.assertNotIn("AUDD-PRIVATE-SECRET", payload)
            self.assertNotIn("SPOTIFY-ID-SECRET", payload)
            self.assertNotIn("SPOTIFY-PRIVATE-SECRET", payload)
            self.assertTrue(result["configuration"]["providers"]["audd"]["configured"])
            self.assertTrue(result["configuration"]["providers"]["acoustid"]["configured"])
            self.assertEqual(result["version"], AVACHIN_VERSION)

    def test_status_cli_returns_machine_readable_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/avachin_status.py", "--json", "--compact"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status_schema_version"], 1)
        self.assertEqual(payload["version"], AVACHIN_VERSION)
        self.assertIn("tools", payload)
        self.assertIn("fingerprints", payload)
        self.assertIn("audd_budget", payload)
        self.assertIn("warnings", payload)


if __name__ == "__main__":
    unittest.main()
