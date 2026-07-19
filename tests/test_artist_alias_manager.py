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

from tools import fingerprint_store_v2 as store  # noqa: E402
from tools import review_service  # noqa: E402
from tools.artist_alias_controller import ArtistAliasController  # noqa: E402
from tools.artist_alias_core import artist_alias_key, register_alias, resolve_artist  # noqa: E402
from tools.artist_alias_runtime import install_artist_alias_hook  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


class ArtistAliasManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "fingerprints.sqlite3"
        conn = review_service.connect(self.db_path)
        try:
            with conn:
                self.moein_spaced = store.upsert_recording(
                    conn,
                    artist="Moein Z",
                    title="Naareye Chah",
                    album="Singles",
                    source="test",
                )
                store.upsert_audio_file(
                    conn,
                    recording_id=self.moein_spaced,
                    audio_sha256="moein-spaced-audio",
                    source_path=str(self.root / "Moein Z" / "Singles" / "Naareye Chah.mp3"),
                    duration_seconds=180.0,
                )
                self.moein_compact = store.upsert_recording(
                    conn,
                    artist="MoeinZ",
                    title="Hamin Havali",
                    album="Singles",
                    source="test",
                )
                store.upsert_audio_file(
                    conn,
                    recording_id=self.moein_compact,
                    audio_sha256="moein-compact-audio",
                    source_path=str(self.root / "MoeinZ" / "Singles" / "Hamin Havali.mp3"),
                    duration_seconds=190.0,
                )
                dang_spaced = store.upsert_recording(
                    conn,
                    artist="Dang Show",
                    title="A",
                    album="Singles",
                    source="test",
                )
                store.upsert_audio_file(
                    conn,
                    recording_id=dang_spaced,
                    audio_sha256="dang-spaced",
                    source_path=str(self.root / "Dang Show" / "Singles" / "A.mp3"),
                    duration_seconds=100.0,
                )
                dang_compact = store.upsert_recording(
                    conn,
                    artist="Dangshow",
                    title="B",
                    album="Singles",
                    source="test",
                )
                store.upsert_audio_file(
                    conn,
                    recording_id=dang_compact,
                    audio_sha256="dang-compact",
                    source_path=str(self.root / "Dangshow" / "Singles" / "B.mp3"),
                    duration_seconds=101.0,
                )
        finally:
            conn.close()
        self.controller = ArtistAliasController(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_compact_key_groups_spacing_and_punctuation_variants(self) -> None:
        self.assertEqual(artist_alias_key("Moein Z"), artist_alias_key("MoeinZ"))
        self.assertEqual(artist_alias_key("Dang-Show"), artist_alias_key("Dang Show"))
        groups = self.controller.artist_groups()
        variants = [set(group["variants"]) for group in groups]
        self.assertIn({"Moein Z", "MoeinZ"}, variants)
        self.assertIn({"Dang Show", "Dangshow"}, variants)

    def test_preview_apply_and_undo_are_local_and_preserve_files(self) -> None:
        preview = self.controller.preview_artist_aliases("Moein Z", ["MoeinZ"])
        self.assertEqual(preview["network_requests"], 0)
        self.assertFalse(preview["music_files_changed"])
        self.assertEqual(preview["recordings_affected"], 2)
        self.assertEqual(preview["audio_files_affected"], 2)
        self.assertEqual(len(preview["source_folders"]), 2)

        result = self.controller.apply_artist_aliases(
            "Moein Z",
            ["MoeinZ"],
            reason="test duplicate artist spelling",
        )
        self.assertEqual(result["network_requests"], 0)
        self.assertFalse(result["music_files_changed"])
        self.assertTrue(Path(result["backup_path"]).is_file())

        conn = review_service.connect(self.db_path)
        try:
            active_artists = {
                str(row[0])
                for row in conn.execute(
                    "SELECT artist FROM recordings WHERE status = 'active' AND artist LIKE 'Moein%'"
                ).fetchall()
            }
            self.assertEqual(active_artists, {"Moein Z"})
            self.assertEqual(resolve_artist(conn, "MoeinZ"), "Moein Z")
            moved = conn.execute(
                "SELECT recording_id FROM audio_files WHERE audio_sha256 = 'moein-compact-audio'"
            ).fetchone()
            self.assertIsNotNone(moved)
            target = conn.execute("SELECT artist FROM recordings WHERE id = ?", (moved[0],)).fetchone()
            self.assertEqual(target[0], "Moein Z")
        finally:
            conn.close()

        undone = self.controller.undo(result["action_id"])
        self.assertEqual(undone["status"], "undone")
        conn = review_service.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT r.artist FROM audio_files af JOIN recordings r ON r.id = af.recording_id "
                "WHERE af.audio_sha256 = 'moein-compact-audio'"
            ).fetchone()
            self.assertEqual(row[0], "MoeinZ")
            self.assertEqual(resolve_artist(conn, "MoeinZ"), "MoeinZ")
        finally:
            conn.close()

    def test_future_upserts_use_the_canonical_artist_without_online_lookup(self) -> None:
        conn = review_service.connect(self.db_path)
        try:
            with conn:
                register_alias(conn, "MoeinZ", "Moein Z")
                register_alias(conn, "Moein Z", "Moein Z")
            install_artist_alias_hook()
            with conn:
                recording_id = store.upsert_recording(
                    conn,
                    artist="MoeinZ",
                    title="Future Track",
                    album="Singles",
                    source="test",
                )
            row = conn.execute("SELECT artist FROM recordings WHERE id = ?", (recording_id,)).fetchone()
            self.assertEqual(row[0], "Moein Z")
        finally:
            conn.close()

    def test_gui_check_and_windows_launcher_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/avachin_review_alias_gui.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["version"], AVACHIN_VERSION)
        self.assertTrue(payload["artist_alias_manager"])
        self.assertTrue(payload["alias_runtime_hook"])
        self.assertEqual(payload["network_requests"], 0)
        self.assertFalse(payload["music_files_changed"])

        launcher = (PROJECT_ROOT / "scripts" / "windows" / "review_center.bat").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("avachin_review_alias_gui.py", launcher)
        self.assertIn("zero audd requests", launcher)
        self.assertNotIn("--apply", launcher)


if __name__ == "__main__":
    unittest.main()
