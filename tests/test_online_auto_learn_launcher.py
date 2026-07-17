#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_online_auto_learn_launcher as auto  # noqa: E402


class OnlineAutoLearnTests(unittest.TestCase):
    def audio(self, *, title: str = "", artist: str = ""):
        return auto.app.AudioInfo(tags=auto.app.Tags(title=title, artist=artist))

    def candidate(
        self,
        *,
        source: str = "audd",
        confidence: float = 96.0,
        consensus: list[str] | None = None,
    ):
        return auto.app.Candidate(
            source=source,
            title="New Song",
            artist="Known Artist",
            album="New Album",
            confidence=confidence,
            consensus_sources=consensus or [source],
            musicbrainz_recording_id="mb-recording-1",
            spotify_track_id="spotify-track-1",
            apple_track_id="apple-track-1",
            isrc="IRAAA2600001",
        )

    def run_wrapper(self, candidate, audio=None, config=None):
        audio = audio or self.audio()
        config = dict(config or {})
        learned = {
            "id": 12,
            "recording_id": "rec_test",
            "schema_version": 2,
            "external_ids_added": 4,
        }
        with mock.patch.object(
            auto,
            "_ORIGINAL_DETERMINE_CANDIDATE",
            return_value=(candidate, []),
        ), mock.patch.object(
            auto.fingerprint_library,
            "learn_file",
            return_value=learned,
        ) as learn:
            result, errors = auto._determine_candidate_with_online_auto_learn(
                Path(r"C:\Test\Untitled - Unknown Artist.mp3"),
                audio,
                "",
                False,
                config,
                object(),
                85.0,
                True,
                False,
                "_Unknown Artist",
                Path(r"C:\Tools\fpcalc.exe"),
            )
        return result, errors, learn

    def test_trusted_acoustic_unknown_input_is_learned(self) -> None:
        result, errors, learn = self.run_wrapper(self.candidate())

        self.assertEqual(errors, [])
        learn.assert_called_once()
        kwargs = learn.call_args.kwargs
        self.assertEqual(kwargs["source"], "online:audd")
        self.assertEqual(kwargs["artist"], "Known Artist")
        self.assertEqual(kwargs["title"], "New Song")
        self.assertEqual(len(kwargs["external_ids"]), 4)
        self.assertEqual(result.evidence["online_auto_learn_status"], "learned")
        self.assertEqual(result.evidence["online_auto_learn_recording_id"], "rec_test")

    def test_reliable_existing_tags_are_not_learned(self) -> None:
        result, errors, learn = self.run_wrapper(
            self.candidate(),
            audio=self.audio(title="Existing Song", artist="Existing Artist"),
        )

        self.assertEqual(errors, [])
        learn.assert_not_called()
        self.assertEqual(result.evidence["online_auto_learn_status"], "skipped")
        self.assertEqual(
            result.evidence["online_auto_learn_reason"],
            "input-identity-already-reliable",
        )

    def test_single_catalog_provider_is_not_enough(self) -> None:
        result, _, learn = self.run_wrapper(
            self.candidate(source="musicbrainz", confidence=100.0, consensus=["musicbrainz"])
        )

        learn.assert_not_called()
        self.assertEqual(result.evidence["online_auto_learn_reason"], "catalog-consensus-below:2")

    def test_two_provider_catalog_consensus_can_be_learned(self) -> None:
        result, errors, learn = self.run_wrapper(
            self.candidate(
                source="musicbrainz",
                confidence=100.0,
                consensus=["musicbrainz", "apple"],
            )
        )

        self.assertEqual(errors, [])
        learn.assert_called_once()
        self.assertEqual(result.evidence["online_auto_learn_status"], "learned")

    def test_learning_failure_is_non_fatal(self) -> None:
        candidate = self.candidate()
        with mock.patch.object(
            auto,
            "_ORIGINAL_DETERMINE_CANDIDATE",
            return_value=(candidate, []),
        ), mock.patch.object(
            auto.fingerprint_library,
            "learn_file",
            side_effect=RuntimeError("disk unavailable"),
        ):
            result, errors = auto._determine_candidate_with_online_auto_learn(
                Path(r"C:\Test\Untitled - Unknown Artist.mp3"),
                self.audio(),
                "",
                False,
                {},
                object(),
                85.0,
                True,
                False,
                "_Unknown Artist",
                Path(r"C:\Tools\fpcalc.exe"),
            )

        self.assertIs(result, candidate)
        self.assertEqual(result.evidence["online_auto_learn_status"], "failed")
        self.assertTrue(any("disk unavailable" in item for item in errors))

    def test_local_candidate_is_never_relearned(self) -> None:
        candidate = self.candidate(source="local_fingerprint", confidence=99.0)
        result, _, learn = self.run_wrapper(candidate)

        learn.assert_not_called()
        self.assertEqual(
            result.evidence["online_auto_learn_reason"],
            "source-not-allowed:local_fingerprint",
        )


if __name__ == "__main__":
    unittest.main()
