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
from tools import partial_fingerprint_store as partial_store  # noqa: E402
from tools.review_controller import ReviewController  # noqa: E402


def fingerprint(seed: int, count: int = 600) -> list[int]:
    return [((index + seed) * 2654435761 ^ seed * 2246822519) & 0xFFFFFFFF for index in range(count)]


def add_track(conn: sqlite3.Connection, *, artist: str, title: str, path: str, audio_hash: str, raw: list[int]) -> tuple[str, int, int]:
    recording_id = store.upsert_recording(conn, artist=artist, title=title, album="Singles", source="test", confidence=99.0)
    audio_file_id = store.upsert_audio_file(
        conn,
        recording_id=recording_id,
        audio_sha256=audio_hash,
        source_path=path,
        duration_seconds=120.0,
    )
    fingerprint_id = store.replace_fingerprint(
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
    partial_store.ensure_segment_schema(conn)
    partial_store.replace_segments_for_fingerprint(conn, fingerprint_id)
    return recording_id, audio_file_id, fingerprint_id


class ReviewCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "fingerprints.sqlite3"
        conn = partial_store.connect(self.db_path)
        with conn:
            self.faded_id, self.audio_id, self.fp_id = add_track(
                conn,
                artist="Alan Walker",
                title="Faded",
                path=str(self.root / "Faded - Alan Walker.mp3"),
                audio_hash="audio-faded-but-pedar",
                raw=fingerprint(7),
            )
            self.pedar_id, self.pedar_audio_id, _ = add_track(
                conn,
                artist="Shahrokh",
                title="Pedar",
                path=str(self.root / "Pedar - Shahrokh.mp3"),
                audio_hash="audio-pedar",
                raw=fingerprint(19),
            )
        conn.close()
        self.controller = ReviewController(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def row(self, table: str, row_id: int | str) -> sqlite3.Row:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
            assert row is not None
            return row
        finally:
            conn.close()

    def segment_frames(self, recording_id: str) -> int:
        conn = sqlite3.connect(self.db_path)
        try:
            return int(
                conn.execute(
                    "SELECT COALESCE(SUM(frame_count), 0) FROM fingerprint_segments WHERE recording_id = ?",
                    (recording_id,),
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def test_reassign_moves_all_acoustic_rows_and_undoes(self) -> None:
        result = self.controller.reassign(
            self.audio_id,
            artist="Shahrokh",
            title="Pedar",
            album="Singles",
            reason="manual playback confirmed Pedar",
        )
        self.assertEqual(result["target_recording_id"], self.pedar_id)
        self.assertEqual(self.row("audio_files", self.audio_id)["recording_id"], self.pedar_id)
        self.assertEqual(self.row("fingerprints", self.fp_id)["recording_id"], self.pedar_id)
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.controller.undo(result["action_id"])
        self.assertEqual(self.row("audio_files", self.audio_id)["recording_id"], self.faded_id)
        self.assertEqual(self.row("fingerprints", self.fp_id)["recording_id"], self.faded_id)

    def test_revoke_neutralizes_segments_and_undo_rebuilds(self) -> None:
        result = self.controller.revoke(self.faded_id, reason="wrong acoustic association")
        self.assertEqual(self.row("recordings", self.faded_id)["status"], "revoked")
        self.assertGreater(result["segments_disabled"], 0)
        self.assertEqual(self.segment_frames(self.faded_id), 0)
        undone = self.controller.undo(result["action_id"])
        self.assertEqual(self.row("recordings", self.faded_id)["status"], "active")
        self.assertGreater(undone["segments_rebuilt"], 0)
        self.assertGreater(self.segment_frames(self.faded_id), 0)

    def test_merge_and_undo(self) -> None:
        result = self.controller.merge(self.faded_id, self.pedar_id, reason="duplicate identity")
        self.assertEqual(self.row("recordings", self.faded_id)["status"], "merged")
        self.assertEqual(self.row("audio_files", self.audio_id)["recording_id"], self.pedar_id)
        self.controller.undo(result["action_id"])
        self.assertEqual(self.row("recordings", self.faded_id)["status"], "active")
        self.assertEqual(self.row("audio_files", self.audio_id)["recording_id"], self.faded_id)

    def test_manual_learning_is_segmented_audited_and_undoable(self) -> None:
        unknown = self.root / "Unknown Artist - Untitled.mp3"
        unknown.write_bytes(b"audio")
        raw = fingerprint(31)
        with mock.patch("tools.review_controller.local_fp.raw_fingerprint", return_value=(120.0, raw)), mock.patch(
            "tools.review_controller.local_fp.audio_sha256", return_value="manual-audio"
        ):
            result = self.controller.learn_rejected_file(
                unknown,
                artist="Verified Artist",
                title="Verified Title",
                album="Singles",
                reason="listened manually",
            )
        self.assertGreater(result["segments"], 0)
        self.assertEqual(self.controller.history()[0]["action_type"], "manual-learn")
        self.controller.undo(result["action_id"])
        conn = sqlite3.connect(self.db_path)
        try:
            count = int(conn.execute("SELECT COUNT(*) FROM audio_files WHERE id = ?", (result["audio_file_id"],)).fetchone()[0])
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_queue_returns_only_unsafe_items(self) -> None:
        report = self.root / "detection-report.json"
        report.write_text(
            json.dumps(
                {
                    "summary": {"total": 2, "REJECT": 1, "LOCAL_MATCH": 1},
                    "detections": [
                        {
                            "source_path": "C:/Music/Unknown.mp3",
                            "decision": "REJECT",
                            "decision_reason": "identity-is-missing-or-placeholder",
                            "safe_to_apply": False,
                            "artist": "Unknown Artist",
                            "title": "Untitled",
                            "confidence": {"overall": 12.0},
                            "evidence": {"provider": "none"},
                        },
                        {
                            "source_path": "C:/Music/Good.mp3",
                            "decision": "LOCAL_MATCH",
                            "safe_to_apply": True,
                            "artist": "Good",
                            "title": "Song",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        queue = self.controller.queue(report)
        self.assertEqual(len(queue["items"]), 1)
        self.assertEqual(queue["items"][0]["decision"], "REJECT")


if __name__ == "__main__":
    unittest.main()
