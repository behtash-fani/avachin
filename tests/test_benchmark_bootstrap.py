#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_bootstrap import bootstrap_manifest  # noqa: E402
from tools.benchmark_contract import BenchmarkManifest  # noqa: E402


class BenchmarkBootstrapTests(unittest.TestCase):
    def make_db(self, root: Path) -> tuple[Path, list[Path]]:
        sources = [root / "studio.mp3", root / "live.mp3"]
        sources[0].write_bytes(b"studio audio")
        sources[1].write_bytes(b"live audio")
        db = root / "fingerprints.sqlite3"
        connection = sqlite3.connect(db)
        try:
            connection.executescript(
                """
                CREATE TABLE recordings (
                    id TEXT PRIMARY KEY,
                    artist TEXT NOT NULL,
                    title TEXT NOT NULL,
                    album TEXT,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL
                );
                CREATE TABLE audio_files (
                    id INTEGER PRIMARY KEY,
                    recording_id TEXT NOT NULL,
                    source_path TEXT,
                    duration_seconds REAL
                );
                CREATE TABLE external_ids (
                    id INTEGER PRIMARY KEY,
                    recording_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    external_id TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                "INSERT INTO recordings VALUES (?, ?, ?, ?, 'active', 99)",
                [
                    ("rec_studio", "Artist", "Song", "Studio Album"),
                    ("rec_live", "Artist", "Song", "Live Album"),
                ],
            )
            connection.executemany(
                "INSERT INTO audio_files VALUES (?, ?, ?, ?)",
                [
                    (1, "rec_studio", str(sources[0]), 200.0),
                    (2, "rec_live", str(sources[1]), 230.0),
                ],
            )
            connection.executemany(
                "INSERT INTO external_ids VALUES (?, ?, ?, 'recording', ?)",
                [
                    (1, "rec_studio", "isrc", "IRAAA2600001"),
                    (2, "rec_live", "musicbrainz", "mb-live"),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        return db, sources

    def test_bootstrap_copies_sources_and_preserves_originals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db, sources = self.make_db(root)
            original_hashes = [source.read_bytes() for source in sources]
            corpus = root / "corpus"
            manifest_path = corpus / "manifest.json"
            result = bootstrap_manifest(
                db_path=db,
                corpus_root=corpus,
                output_manifest=manifest_path,
                limit=10,
                validation_percent=50,
            )
            self.assertEqual(result["references"], 2)
            self.assertTrue(result["review_required"])
            self.assertEqual(
                [source.read_bytes() for source in sources],
                original_hashes,
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["references"]), 2)
            self.assertTrue(
                all(reference["hard_negative_group"] for reference in payload["references"])
            )
            self.assertEqual(
                {reference["split"] for reference in payload["references"]},
                {"validation", "test"},
            )
            for reference in payload["references"]:
                self.assertTrue((corpus / reference["path"]).is_file())
            validated = BenchmarkManifest.load(manifest_path)
            self.assertEqual(len(validated.references), 2)
            self.assertIn("avachin:rec_studio", validated.identity_owner_map())

    def test_missing_v2_tables_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = root / "bad.sqlite3"
            sqlite3.connect(db).close()
            with self.assertRaisesRegex(ValueError, "V2 identity tables"):
                bootstrap_manifest(
                    db_path=db,
                    corpus_root=root / "corpus",
                    output_manifest=root / "manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
