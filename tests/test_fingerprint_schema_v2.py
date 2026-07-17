#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import fingerprint_store_v2 as store  # noqa: E402
from tools import local_fingerprint_library as library  # noqa: E402


LEGACY_SCHEMA = """
CREATE TABLE local_fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_sha256 TEXT,
    fingerprint_sha256 TEXT NOT NULL,
    source_path TEXT,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    duration_seconds REAL,
    fingerprint_frames INTEGER NOT NULL,
    raw_fingerprint_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence REAL NOT NULL DEFAULT 100.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def connect_memory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def insert_legacy_baazi(conn: sqlite3.Connection, fingerprint: list[int]) -> None:
    conn.execute(LEGACY_SCHEMA)
    conn.execute(
        """
        INSERT INTO local_fingerprints (
            audio_sha256, fingerprint_sha256, source_path, artist, title,
            album, duration_seconds, fingerprint_frames, raw_fingerprint_json,
            source, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "audio-baazi-v1",
            "fingerprint-baazi-v1",
            r"C:\Music\Baazi - Siavash Ghomayshi.mp3",
            "Siavash Ghomayshi",
            "Baazi",
            "",
            180.0,
            len(fingerprint),
            json.dumps(fingerprint, separators=(",", ":")),
            "manual",
            100.0,
            "2026-07-17T00:00:00+00:00",
            "2026-07-17T00:00:00+00:00",
        ),
    )
    conn.commit()


class FingerprintSchemaV2Tests(unittest.TestCase):
    def test_legacy_migration_is_non_destructive_and_idempotent(self) -> None:
        conn = connect_memory()
        try:
            insert_legacy_baazi(conn, list(range(40)))
            first = store.ensure_schema(conn)
            second = store.ensure_schema(conn)
            summary = store.stats(conn)

            self.assertEqual(first["legacy_rows_migrated"], 1)
            self.assertEqual(second["legacy_rows_migrated"], 0)
            self.assertEqual(summary["schema_version"], 2)
            self.assertEqual(summary["recordings"], 1)
            self.assertEqual(summary["audio_files"], 1)
            self.assertEqual(summary["fingerprints"], 1)
            self.assertEqual(summary["legacy_rows_imported"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM local_fingerprints").fetchone()[0], 1)
        finally:
            conn.close()

    def test_one_recording_can_have_multiple_audio_encodings(self) -> None:
        conn = connect_memory()
        try:
            store.ensure_schema(conn)
            recording_a = store.upsert_recording(
                conn,
                artist="Siavash Ghomayshi",
                title="Baazi",
                album="",
                source="test",
            )
            recording_b = store.upsert_recording(
                conn,
                artist="  SIAVASH   GHOMAYSHI ",
                title="BAAZI",
                album="",
                source="test",
            )
            self.assertEqual(recording_a, recording_b)

            for index, audio_hash in enumerate(("encoding-128", "encoding-320"), start=1):
                audio_file_id = store.upsert_audio_file(
                    conn,
                    recording_id=recording_a,
                    audio_sha256=audio_hash,
                    source_path=f"encoding-{index}.mp3",
                    duration_seconds=180.0 + index,
                )
                store.replace_fingerprint(
                    conn,
                    recording_id=recording_a,
                    audio_file_id=audio_file_id,
                    fingerprint_sha256=f"fp-{index}",
                    fingerprint_frames=40,
                    raw_fingerprint_json=json.dumps([index] * 40),
                    duration_seconds=180.0 + index,
                    source="test",
                )
            conn.commit()
            summary = store.stats(conn)
            self.assertEqual(summary["recordings"], 1)
            self.assertEqual(summary["audio_files"], 2)
            self.assertEqual(summary["fingerprints"], 2)
        finally:
            conn.close()

    def test_relearning_same_audio_replaces_fingerprint_without_duplicates(self) -> None:
        conn = connect_memory()
        try:
            store.ensure_schema(conn)
            recording_id = store.upsert_recording(
                conn,
                artist="Siavash Ghomayshi",
                title="Baazi",
                source="test",
            )
            audio_file_a = store.upsert_audio_file(
                conn,
                recording_id=recording_id,
                audio_sha256="same-audio",
                source_path="old.mp3",
                duration_seconds=180.0,
            )
            fingerprint_a = store.replace_fingerprint(
                conn,
                recording_id=recording_id,
                audio_file_id=audio_file_a,
                fingerprint_sha256="old-fingerprint",
                fingerprint_frames=40,
                raw_fingerprint_json=json.dumps([1] * 40),
                duration_seconds=180.0,
            )
            audio_file_b = store.upsert_audio_file(
                conn,
                recording_id=recording_id,
                audio_sha256="same-audio",
                source_path="new.mp3",
                duration_seconds=180.0,
            )
            fingerprint_b = store.replace_fingerprint(
                conn,
                recording_id=recording_id,
                audio_file_id=audio_file_b,
                fingerprint_sha256="new-fingerprint",
                fingerprint_frames=40,
                raw_fingerprint_json=json.dumps([2] * 40),
                duration_seconds=180.0,
            )
            conn.commit()

            self.assertEqual(audio_file_a, audio_file_b)
            self.assertEqual(fingerprint_a, fingerprint_b)
            summary = store.stats(conn)
            self.assertEqual(summary["audio_files"], 1)
            self.assertEqual(summary["fingerprints"], 1)
            row = conn.execute("SELECT fingerprint_sha256 FROM fingerprints").fetchone()
            self.assertEqual(row[0], "new-fingerprint")
        finally:
            conn.close()

    def test_existing_match_api_reads_migrated_schema(self) -> None:
        fingerprint = [123456789] * 40
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "fingerprints.sqlite3"
            audio_path = root / "Untitled - Unknown Artist.mp3"
            audio_path.write_bytes(b"test-audio")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                insert_legacy_baazi(conn, fingerprint)
            finally:
                conn.close()

            with mock.patch.object(
                library,
                "raw_fingerprint",
                return_value=(180.0, fingerprint),
            ):
                result = library.match_file(
                    audio_path,
                    threshold=86.0,
                    duration_tolerance_seconds=8.0,
                    db_path=db_path,
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["title"], "Baazi")
            self.assertEqual(result["artist"], "Siavash Ghomayshi")
            self.assertEqual(result["schema_version"], 2)
            self.assertTrue(str(result["recording_id"]).startswith("rec_"))

    def test_external_ids_are_deduplicated(self) -> None:
        conn = connect_memory()
        try:
            store.ensure_schema(conn)
            recording_id = store.upsert_recording(
                conn,
                artist="Siavash Ghomayshi",
                title="Baazi",
            )
            identifiers = [
                ("musicbrainz", "recording", "mbid-1"),
                ("musicbrainz", "recording", "mbid-1"),
                ("spotify", "track", "spotify-1"),
            ]
            added = store.add_external_ids(conn, recording_id, identifiers)
            conn.commit()
            self.assertEqual(added, 2)
            self.assertEqual(store.stats(conn)["external_ids"], 2)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
