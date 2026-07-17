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

from tools import fingerprint_store_v2 as v2  # noqa: E402
from tools import partial_fingerprint_store as partial  # noqa: E402


def synthetic_fingerprint(count: int, salt: int = 0) -> list[int]:
    return [
        ((index * 2654435761) ^ ((index + salt) * 2246822519) ^ (salt * 3266489917))
        & 0xFFFFFFFF
        for index in range(count)
    ]


def insert_recording(conn: sqlite3.Connection, artist: str, title: str, raw: list[int], audio_hash: str) -> int:
    recording_id = v2.upsert_recording(
        conn,
        artist=artist,
        title=title,
        album="Singles",
        source="test",
        confidence=99.0,
    )
    audio_file_id = v2.upsert_audio_file(
        conn,
        recording_id=recording_id,
        audio_sha256=audio_hash,
        source_path=f"C:/Music/{title}.mp3",
        duration_seconds=120.0,
    )
    return v2.replace_fingerprint(
        conn,
        recording_id=recording_id,
        audio_file_id=audio_file_id,
        fingerprint_sha256=f"fp-{audio_hash}",
        fingerprint_frames=len(raw),
        raw_fingerprint_json=json.dumps(raw, separators=(",", ":")),
        duration_seconds=120.0,
        source="test",
        confidence=99.0,
    )


class PartialFingerprintV3Tests(unittest.TestCase):
    def test_segment_windows_cover_last_part(self) -> None:
        raw = synthetic_fingerprint(1200)
        windows = partial.segment_windows(raw, 120.0)
        self.assertGreater(len(windows), 5)
        self.assertEqual(windows[0]["start_frame"], 0)
        self.assertEqual(windows[-1]["end_frame"], len(raw))
        self.assertTrue(all(item["frame_count"] >= 120 for item in windows))

    def test_partial_similarity_finds_middle_clip(self) -> None:
        raw = synthetic_fingerprint(1200, salt=7)
        clip = raw[510:690]
        reference = raw[480:720]
        score = partial.partial_similarity(clip, reference)
        self.assertGreater(score, 99.0)

    def test_schema_backfills_and_matches_middle_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "fingerprints.sqlite3"
            clip_path = root / "Untitled - Unknown Artist.mp3"
            clip_path.write_bytes(b"test-audio")
            raw = synthetic_fingerprint(1200, salt=11)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            v2.ensure_schema(conn)
            with conn:
                insert_recording(conn, "Alan Walker", "Faded", raw, "audio-faded")
            conn.close()

            stats = partial.ensure_database(db_path)
            self.assertEqual(stats["schema_version"], 3)
            self.assertGreater(stats["segments"], 0)

            clip = raw[500:700]
            with mock.patch.object(partial.local_fp, "raw_fingerprint", return_value=(20.0, clip)):
                match = partial.match_file_partial(
                    clip_path,
                    db_path=db_path,
                    threshold=84.0,
                )
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match["title"], "Faded")
            self.assertEqual(match["artist"], "Alan Walker")
            self.assertEqual(match["match_mode"], "segment")
            self.assertGreater(match["score"], 99.0)

    def test_ambiguous_equal_recordings_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "fingerprints.sqlite3"
            clip_path = root / "Untitled - Unknown Artist.mp3"
            clip_path.write_bytes(b"test-audio")
            raw = synthetic_fingerprint(1200, salt=19)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            v2.ensure_schema(conn)
            with conn:
                insert_recording(conn, "Artist One", "Song One", raw, "audio-one")
                insert_recording(conn, "Artist Two", "Song Two", raw, "audio-two")
            conn.close()
            partial.ensure_database(db_path)

            with mock.patch.object(partial.local_fp, "raw_fingerprint", return_value=(20.0, raw[400:600])):
                match = partial.match_file_partial(
                    clip_path,
                    db_path=db_path,
                    threshold=84.0,
                    minimum_margin=2.0,
                )
            self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
