#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_local_first_launcher as runtime  # noqa: E402


class LocalFirstLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_local_lookup = runtime.launcher._identify_by_local_fingerprint
        self.original_fallback = runtime._ORIGINAL_DETERMINE_CANDIDATE

    def tearDown(self) -> None:
        runtime.launcher._identify_by_local_fingerprint = self.original_local_lookup
        runtime._ORIGINAL_DETERMINE_CANDIDATE = self.original_fallback

    @staticmethod
    def audio(album: str = "Broken Album") -> SimpleNamespace:
        return SimpleNamespace(tags=SimpleNamespace(album=album))

    @staticmethod
    def candidate(
        source: str = "local_fingerprint",
        *,
        title: str = "Baazi",
        album: str = "Baazi",
    ):
        return runtime.app.Candidate(
            source=source,
            title=title,
            artist="Siavash Ghomayshi",
            album=album,
            album_artist="Siavash Ghomayshi",
            confidence=96.0,
            title_similarity=100.0,
            artist_similarity=100.0,
            duration_similarity=98.0,
            consensus_sources=[source],
            evidence={},
        )

    def test_local_match_short_circuits_every_online_path_in_offline_mode(self) -> None:
        local_candidate = self.candidate()
        calls = []

        def local_lookup(source, fpcalc_path, config):
            calls.append((source, fpcalc_path, config))
            return local_candidate, []

        def forbidden_fallback(*args, **kwargs):
            self.fail("normal catalog/fingerprint pipeline must not run after a local match")

        runtime.launcher._identify_by_local_fingerprint = local_lookup
        runtime._ORIGINAL_DETERMINE_CANDIDATE = forbidden_fallback

        result, errors = runtime._determine_candidate_local_first(
            Path("Untitled - Unknown Artist.mp3"),
            self.audio(),
            "",
            False,
            {"local_fingerprint_library_enabled": True},
            object(),
            85.0,
            False,
            True,
            "_Unknown Artist",
            Path("fpcalc.exe"),
        )

        self.assertIs(result, local_candidate)
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.source, "local_fingerprint")
        self.assertTrue(result.evidence["local_first"])
        self.assertTrue(result.evidence["local_first_offline"])
        self.assertTrue(result.evidence["online_lookup_skipped"])

    def test_local_miss_falls_through_and_preserves_local_errors(self) -> None:
        fallback_candidate = self.candidate(source="existing-tags")
        received = {}

        def local_lookup(source, fpcalc_path, config):
            return None, ["Local fingerprint: test warning"]

        def fallback(*args):
            received["args"] = args
            return fallback_candidate, ["Catalog: test warning"]

        runtime.launcher._identify_by_local_fingerprint = local_lookup
        runtime._ORIGINAL_DETERMINE_CANDIDATE = fallback

        result, errors = runtime._determine_candidate_local_first(
            Path("unknown.mp3"),
            self.audio(),
            "",
            False,
            {},
            object(),
            85.0,
            False,
            False,
            "_Unknown Artist",
            None,
        )

        self.assertIs(result, fallback_candidate)
        self.assertEqual(
            errors,
            ["Local fingerprint: test warning", "Catalog: test warning"],
        )
        self.assertEqual(received["args"][0], Path("unknown.mp3"))
        self.assertFalse(received["args"][8])

    def test_safe_local_fingerprint_album_is_trusted_for_single_file_scan(self) -> None:
        candidate = self.candidate(title="Asheghaaneh Tanhaast", album="Baaraan Toee")
        trusted, reason = runtime._album_is_trusted_with_local_fingerprint(
            "Baaraan Toee",
            candidate,
            SimpleNamespace(tracknumber=None),
            1,
            {},
        )
        self.assertTrue(trusted)
        self.assertEqual(reason, "trusted-local-fingerprint-album")
        self.assertTrue(candidate.evidence["local_fingerprint_album_trusted"])

    def test_title_like_local_fingerprint_album_remains_single(self) -> None:
        candidate = self.candidate(title="Baazi", album="Baazi")
        trusted, reason = runtime._album_is_trusted_with_local_fingerprint(
            "Baazi",
            candidate,
            SimpleNamespace(tracknumber=None),
            1,
            {},
        )
        self.assertFalse(trusted)
        self.assertEqual(reason, "album-title-matches-track-title")

    def test_local_fingerprint_album_trust_can_be_disabled(self) -> None:
        candidate = self.candidate(title="Asheghaaneh Tanhaast", album="Baaraan Toee")
        trusted, reason = runtime._album_is_trusted_with_local_fingerprint(
            "Baaraan Toee",
            candidate,
            SimpleNamespace(tracknumber=None),
            1,
            {"trust_single_track_local_fingerprint_album": False},
        )
        self.assertFalse(trusted)
        self.assertEqual(reason, "not-enough-album-evidence")

    def test_installation_is_idempotent(self) -> None:
        installed = runtime.app.determine_candidate
        album_gate = runtime.app.album_is_trusted_for_folder
        runtime.install_local_first_runtime()
        runtime.install_local_first_runtime()
        self.assertIs(runtime.app.determine_candidate, installed)
        self.assertIs(runtime.app.album_is_trusted_for_folder, album_gate)
        self.assertTrue(getattr(installed, "__avachin_local_first__", False))
        self.assertTrue(
            getattr(album_gate, "__avachin_local_fingerprint_album_trust__", False)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
