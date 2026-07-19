#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import review_online  # noqa: E402


class DummyCache:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def candidate(source: str = "acoustid") -> SimpleNamespace:
    return SimpleNamespace(
        source=source,
        title="Verified Song",
        artist="Verified Artist",
        album="Verified Album",
        album_artist="Verified Artist",
        date=None,
        tracknumber=None,
        discnumber=None,
        genre=None,
        isrc="TESTISRC123",
        duration_ms=180000,
        confidence=97.5,
        title_similarity=100.0,
        artist_similarity=100.0,
        duration_similarity=96.0,
        consensus_sources=[source],
        musicbrainz_recording_id="mb-recording",
        musicbrainz_artist_ids=[],
        musicbrainz_release_id=None,
        spotify_track_id=None,
        apple_track_id=None,
        evidence={"fingerprint_score": 0.975},
    )


class ReviewOnlineTests(unittest.TestCase):
    def test_latest_real_report_excludes_newer_benchmark_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real = root / "reports" / "preview-real" / "detection-report.json"
            benchmark = root / "reports" / "benchmark" / "run-new" / "detection-report.json"
            real.parent.mkdir(parents=True)
            benchmark.parent.mkdir(parents=True)
            real.write_text("{}", encoding="utf-8")
            benchmark.write_text("{}", encoding="utf-8")
            benchmark.touch()

            selected = review_online.latest_real_detection_report([root / "reports"])

            self.assertEqual(selected, real.resolve())
            self.assertFalse(review_online.is_benchmark_report(real))
            self.assertTrue(review_online.is_benchmark_report(benchmark))

    def test_benchmark_sample_is_blocked_before_provider_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sample = Path(temp_dir) / "benchmark" / "generated" / "sample-test.mp3"
            with mock.patch.object(review_online, "_catalog_client") as catalog:
                with self.assertRaisesRegex(ValueError, "Benchmark-generated"):
                    review_online.resolve_online_identity(sample)
            catalog.assert_not_called()

    def test_acoustid_result_is_suggestion_only_and_never_learned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "Unknown Artist - Untitled.mp3"
            audio_path.write_bytes(b"test-audio")
            cache = DummyCache()
            audio = SimpleNamespace(tags=SimpleNamespace())
            acoustid_candidate = candidate("acoustid")

            with mock.patch.object(review_online.app, "load_config", return_value={}), mock.patch.object(
                review_online, "_catalog_client", return_value=(cache, object())
            ), mock.patch.object(review_online.app, "read_mp3", return_value=audio), mock.patch.object(
                review_online.app, "find_fpcalc", return_value=Path("fpcalc")
            ), mock.patch.object(
                review_online.base_launcher,
                "_ORIGINAL_IDENTIFY_BY_FINGERPRINT",
                return_value=(acoustid_candidate, []),
            ), mock.patch.object(review_online.base_launcher, "_identify_by_audd") as audd, mock.patch.object(
                review_online.runtime.fingerprint_library, "learn_file"
            ) as learn:
                result = review_online.resolve_online_identity(audio_path)

            self.assertEqual(result["status"], "suggested")
            self.assertEqual(result["provider"], "acoustid")
            self.assertEqual(result["artist"], "Verified Artist")
            self.assertFalse(result["database_changed"])
            self.assertFalse(result["learned"])
            self.assertTrue(result["requires_human_confirmation"])
            self.assertEqual(result["attempted_providers"], ["acoustid"])
            audd.assert_not_called()
            learn.assert_not_called()
            self.assertTrue(cache.closed)

    def test_audd_is_last_fallback_when_acoustid_and_catalog_hints_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "Unknown Artist - Untitled.mp3"
            audio_path.write_bytes(b"test-audio")
            cache = DummyCache()
            audio = SimpleNamespace(tags=SimpleNamespace())
            audd_candidate = candidate("audd")

            with mock.patch.object(review_online.app, "load_config", return_value={}), mock.patch.object(
                review_online, "_catalog_client", return_value=(cache, object())
            ), mock.patch.object(review_online.app, "read_mp3", return_value=audio), mock.patch.object(
                review_online.app, "find_fpcalc", return_value=Path("fpcalc")
            ), mock.patch.object(
                review_online.base_launcher,
                "_ORIGINAL_IDENTIFY_BY_FINGERPRINT",
                return_value=(None, []),
            ), mock.patch.object(review_online, "_reliable_catalog_seeds", return_value=[]), mock.patch.object(
                review_online.base_launcher,
                "_identify_by_audd",
                return_value=(audd_candidate, []),
            ), mock.patch.object(review_online.runtime.fingerprint_library, "learn_file") as learn:
                result = review_online.resolve_online_identity(audio_path)

            self.assertEqual(result["provider"], "audd")
            self.assertEqual(result["attempted_providers"], ["acoustid", "audd"])
            self.assertFalse(result["database_changed"])
            learn.assert_not_called()
            self.assertTrue(cache.closed)

    def test_controller_returns_empty_queue_when_no_real_report_exists(self) -> None:
        controller = review_online.OnlineReviewController()
        with mock.patch.object(review_online, "latest_real_detection_report", return_value=None), mock.patch.object(
            review_online.review_service, "load_review_queue"
        ) as loader:
            result = controller.queue()
        self.assertEqual(result["report_kind"], "none")
        self.assertEqual(result["items"], [])
        loader.assert_not_called()

    def test_explicit_benchmark_report_is_visible_but_online_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample = root / "benchmark" / "generated" / "sample-clean.mp3"
            report = root / "reports" / "benchmark" / "run" / "detection-report.json"
            sample.parent.mkdir(parents=True)
            report.parent.mkdir(parents=True)
            sample.write_bytes(b"test")
            report.write_text(
                json.dumps(
                    {
                        "summary": {"REJECT": 1},
                        "detections": [
                            {
                                "source_path": str(sample),
                                "decision": "REJECT",
                                "decision_reason": "confidence-below-review-threshold",
                                "safe_to_apply": False,
                                "artist": "sample",
                                "title": "sample-clean",
                                "confidence": {"overall": 34.38},
                                "evidence": {"provider": "local-cleanup"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = review_online.OnlineReviewController().queue(report)

            self.assertEqual(result["report_kind"], "benchmark")
            self.assertEqual(len(result["items"]), 1)
            self.assertTrue(result["items"][0]["benchmark_sample"])
            self.assertFalse(result["items"][0]["online_lookup_allowed"])


if __name__ == "__main__":
    unittest.main()
