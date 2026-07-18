#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_detection_launcher as launcher  # noqa: E402


@dataclass
class Tags:
    title: str = ""
    artist: str = ""
    albumartist: str = ""


@dataclass
class Audio:
    tags: Tags = field(default_factory=Tags)
    duration_seconds: float = 200.0


@dataclass
class Candidate:
    source: str = "local_fingerprint"
    title: str = "Song"
    artist: str = "Artist"
    album: str = ""
    confidence: float = 99.0
    title_similarity: float = 100.0
    artist_similarity: float = 100.0
    duration_similarity: float = 100.0
    duration_ms: int = 200000
    consensus_sources: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(
        default_factory=lambda: {
            "local_fingerprint_score": 98,
            "local_fingerprint_recording_id": "rec_1",
        }
    )
    isrc: str | None = None
    musicbrainz_recording_id: str | None = None
    spotify_track_id: str | None = None
    apple_track_id: str | None = None


@dataclass
class RuntimeResult:
    item_type: str
    source_path: str
    status: str
    error: str | None = None


class DetectionQueryTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        with launcher._DETECTIONS_LOCK:
            launcher._DETECTIONS.clear()
            launcher._QUERY_TIMINGS.clear()

    def test_wrapper_records_query_time_in_journal_evidence_and_report(self) -> None:
        candidate = Candidate()

        def fake_resolver(*args: Any, **kwargs: Any):
            del args, kwargs
            time.sleep(0.01)
            return candidate, []

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "track.mp3"
            with mock.patch.object(
                launcher,
                "_ORIGINAL_DETERMINE_CANDIDATE",
                fake_resolver,
            ):
                resolved, errors = launcher._determine_candidate_with_detection_contract(
                    source,
                    Audio(),
                    "Unknown Artist",
                    False,
                    {"local_fingerprint_match_threshold": 86},
                    None,
                    85,
                    False,
                    True,
                    "Unknown Artist",
                    None,
                )
            self.assertEqual(errors, [])
            self.assertGreaterEqual(
                resolved.evidence["detection_query_seconds"],
                0.009,
            )
            legacy = root / "report.csv"

            def legacy_writer(path: Path, results: list[Any]) -> None:
                del results
                path.write_text("legacy\n", encoding="utf-8")

            with mock.patch.object(
                launcher,
                "_ORIGINAL_WRITE_CSV",
                legacy_writer,
            ):
                launcher._write_csv_with_detection_reports(
                    legacy,
                    [RuntimeResult("mp3", str(source), "preview")],
                )
            report = json.loads(
                (root / "detection-report.json").read_text(encoding="utf-8")
            )
            self.assertGreaterEqual(
                report["detections"][0]["query_seconds"],
                0.009,
            )


if __name__ == "__main__":
    unittest.main()
