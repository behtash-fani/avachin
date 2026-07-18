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
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import bulk_index_library as bulk  # noqa: E402
from tools import fingerprint_store_v2 as store  # noqa: E402


def audio_info(title: str, artist: str, album: str = "Singles"):
    return bulk.app.AudioInfo(
        tags=bulk.app.Tags(title=title, artist=artist, albumartist=artist, album=album),
        duration_seconds=180.0,
        bitrate_bps=320000,
        bitrate_mode="CBR",
    )


class BulkIndexLibraryTests(unittest.TestCase):
    def test_preview_reports_eligible_and_invalid_without_learning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "Faded - Alan Walker.mp3"
            invalid = root / "Untitled - Unknown Artist.mp3"
            valid.write_bytes(b"valid")
            invalid.write_bytes(b"invalid")
            db_path = root / "db.sqlite3"
            report_dir = root / "report"

            def fake_read(path: Path):
                if Path(path).name.startswith("Faded"):
                    return audio_info("Faded", "Alan Walker", "Faded")
                return audio_info("Untitled", "Unknown Artist", "")

            def forbidden_learn(*args, **kwargs):
                raise AssertionError("preview must not learn fingerprints")

            with mock.patch.object(bulk.app, "read_mp3", side_effect=fake_read):
                summary = bulk.index_library(
                    root,
                    apply=False,
                    db_path=db_path,
                    report_dir=report_dir,
                    learn_file_func=forbidden_learn,
                )

            self.assertEqual(summary["files_scanned"], 2)
            self.assertEqual(summary["eligible"], 1)
            self.assertEqual(summary["metadata_repair_eligible"], 0)
            self.assertEqual(summary["indexed"], 0)
            self.assertEqual(summary["counts"]["eligible"], 1)
            self.assertEqual(summary["counts"]["skipped"], 1)
            self.assertFalse(db_path.exists())
            self.assertTrue((report_dir / "report.csv").exists())
            self.assertTrue((report_dir / "summary.json").exists())

    def test_missing_album_is_inferred_from_organized_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artist_root = Path(temp_dir) / "Chaartaar"
            album_dir = artist_root / "Baaraan Toee"
            album_dir.mkdir(parents=True)
            song = album_dir / "Asheghaaneh Tanhaast - Chaartaar.mp3"
            song.write_bytes(b"audio")

            with mock.patch.object(
                bulk.app,
                "read_mp3",
                return_value=audio_info("Asheghaaneh Tanhaast", "Chaartaar", ""),
            ):
                metadata, reason = bulk.trusted_metadata(song, artist_root)

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["album"], "Baaraan Toee")
            self.assertEqual(reason, "trusted-tags+album-from-folder")

    def test_singles_folder_is_not_stored_as_album(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artist_root = Path(temp_dir) / "Artist"
            singles = artist_root / "Singles"
            singles.mkdir(parents=True)
            song = singles / "Song - Artist.mp3"
            song.write_bytes(b"audio")

            with mock.patch.object(
                bulk.app,
                "read_mp3",
                return_value=audio_info("Song", "Artist", ""),
            ):
                metadata, _ = bulk.trusted_metadata(song, artist_root)

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["album"], "")

    def test_apply_indexes_unique_audio_and_skips_batch_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Song One - Artist.mp3"
            duplicate = root / "Song One Copy - Artist.mp3"
            second = root / "Song Two - Artist.mp3"
            for path in (first, duplicate, second):
                path.write_bytes(path.name.encode("utf-8"))
            db_path = root / "db.sqlite3"
            report_dir = root / "report"
            learned_calls: list[str] = []

            def fake_read(path: Path):
                name = Path(path).name
                title = "Song Two" if name.startswith("Song Two") else "Song One"
                return audio_info(title, "Artist")

            def fake_hash(path: Path) -> str:
                return "same-audio" if "Song One" in Path(path).name else "second-audio"

            def fake_learn(path: Path, **kwargs):
                learned_calls.append(Path(path).name)
                return {
                    "recording_id": "rec-" + str(len(learned_calls)),
                    "audio_sha256": fake_hash(path),
                }

            with mock.patch.object(bulk.app, "read_mp3", side_effect=fake_read):
                summary = bulk.index_library(
                    root,
                    apply=True,
                    db_path=db_path,
                    report_dir=report_dir,
                    fpcalc_path=root / "fpcalc",
                    learn_file_func=fake_learn,
                    hash_file_func=fake_hash,
                    segment_backfill_func=lambda path: {"schema_version": 3, "segments": 22},
                )

            self.assertEqual(summary["eligible"], 3)
            self.assertEqual(summary["indexed"], 2)
            self.assertEqual(summary["repaired"], 0)
            self.assertEqual(summary["counts"]["indexed"], 2)
            self.assertEqual(summary["counts"]["duplicate-audio-skipped"], 1)
            self.assertEqual(len(learned_calls), 2)
            self.assertEqual(summary["segment_stats"]["schema_version"], 3)

    def test_preview_and_apply_repair_existing_empty_album_without_refingerprinting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artist_root = Path(temp_dir) / "Chaartaar"
            album_dir = artist_root / "Baaraan Toee"
            album_dir.mkdir(parents=True)
            song = album_dir / "Asheghaaneh Tanhaast - Chaartaar.mp3"
            song.write_bytes(b"audio")
            db_path = Path(temp_dir) / "db.sqlite3"

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store.ensure_schema(conn)
            raw = [((index * 2654435761) ^ 12345) & 0xFFFFFFFF for index in range(900)]
            with conn:
                old_recording_id = store.upsert_recording(
                    conn,
                    artist="Chaartaar",
                    title="Asheghaaneh Tanhaast",
                    album="",
                    source="bulk-index:trusted-tags",
                    confidence=98.0,
                )
                audio_file_id = store.upsert_audio_file(
                    conn,
                    recording_id=old_recording_id,
                    audio_sha256="audio-hash",
                    source_path=str(song),
                    duration_seconds=180.0,
                )
                store.replace_fingerprint(
                    conn,
                    recording_id=old_recording_id,
                    audio_file_id=audio_file_id,
                    fingerprint_sha256="fingerprint-hash",
                    fingerprint_frames=len(raw),
                    raw_fingerprint_json=json.dumps(raw),
                    duration_seconds=180.0,
                    source="bulk-index:trusted-tags",
                    confidence=98.0,
                )
            conn.close()

            with mock.patch.object(
                bulk.app,
                "read_mp3",
                return_value=audio_info("Asheghaaneh Tanhaast", "Chaartaar", ""),
            ):
                preview = bulk.index_library(
                    artist_root,
                    apply=False,
                    db_path=db_path,
                    report_dir=Path(temp_dir) / "preview-report",
                )
                applied = bulk.index_library(
                    artist_root,
                    apply=True,
                    db_path=db_path,
                    report_dir=Path(temp_dir) / "apply-report",
                    segment_backfill_func=lambda path: {"schema_version": 3, "segments": 1},
                )

            self.assertEqual(preview["eligible"], 0)
            self.assertEqual(preview["metadata_repair_eligible"], 1)
            self.assertEqual(preview["counts"]["metadata-repair-eligible"], 1)
            self.assertEqual(applied["indexed"], 0)
            self.assertEqual(applied["repaired"], 1)
            self.assertEqual(applied["counts"]["metadata-repaired"], 1)
            self.assertTrue(Path(applied["backup_path"]).exists())

            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute(
                    """
                    SELECT rec.id, rec.album, af.recording_id, fp.recording_id
                    FROM audio_files AS af
                    JOIN recordings AS rec ON rec.id = af.recording_id
                    JOIN fingerprints AS fp ON fp.audio_file_id = af.id
                    WHERE af.source_path = ?
                    """,
                    (str(song),),
                ).fetchone()
                old_count = conn.execute(
                    "SELECT COUNT(*) FROM recordings WHERE id = ?",
                    (old_recording_id,),
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[1], "Baaraan Toee")
            self.assertEqual(row[0], row[2])
            self.assertEqual(row[0], row[3])
            self.assertEqual(old_count, 0)

    def test_existing_source_path_is_not_reindexed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            song = root / "Faded - Alan Walker.mp3"
            song.write_bytes(b"audio")
            db_path = root / "db.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE audio_files (source_path TEXT, audio_sha256 TEXT)"
            )
            conn.execute(
                "INSERT INTO audio_files (source_path, audio_sha256) VALUES (?, ?)",
                (str(song), "hash"),
            )
            conn.commit()
            conn.close()

            with mock.patch.object(bulk.app, "read_mp3", return_value=audio_info("Faded", "Alan Walker")):
                summary = bulk.index_library(
                    root,
                    apply=False,
                    db_path=db_path,
                    report_dir=root / "report",
                )

            self.assertEqual(summary["eligible"], 0)
            self.assertEqual(summary["metadata_repair_eligible"], 0)
            self.assertEqual(summary["counts"]["already-indexed-path"], 1)

    def test_sqlite_backup_contains_committed_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "source.sqlite3"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sample (value TEXT)")
            conn.execute("INSERT INTO sample (value) VALUES ('safe')")
            conn.commit()
            conn.close()

            backup = bulk.backup_database(db_path, root / "backups")
            self.assertIsNotNone(backup)
            assert backup is not None
            restored = sqlite3.connect(backup)
            try:
                row = restored.execute("SELECT value FROM sample").fetchone()
            finally:
                restored.close()
            self.assertEqual(row[0], "safe")

    def test_direct_cli_help_from_project_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/bulk_index_library.py", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("already-organized MP3 library", completed.stdout)


if __name__ == "__main__":
    unittest.main()
