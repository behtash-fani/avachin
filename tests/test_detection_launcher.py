#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_detection_launcher as launcher  # noqa: E402
from tools.detection_contract import DetectionDecision  # noqa: E402


@dataclass
class Tags:
    title: str = ""
    artist: str = ""
    albumartist: str = ""


@dataclass
class Audio:
    tags: Tags
    duration_seconds: float = 200.0


@dataclass
class Candidate:
    source: str = "local_fingerprint"
    title: str = "Pedar"
    artist: str = "Shahrokh"
    album: str = ""
    confidence: float = 99.0
    title_similarity: float = 100.0
    artist_similarity: float = 100.0
    duration_similarity: float = 100.0
    duration_ms: int = 200000
    consensus_sources: list[str] = field(
        default_factory=lambda: ["local_fingerprint"]
    )
    evidence: dict[str, Any] = field(
        default_factory=lambda: {
            "local_fingerprint_score": 97.0,
            "local_first": True,
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


class DetectionLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        with launcher._DETECTIONS_LOCK:
            launcher._DETECTIONS.clear()

    def test_runtime_installs_detection_and_report_wrappers(self) -> None:
        self.assertTrue(
            getattr(
                launcher.app.determine_candidate,
                "__avachin_detection_contract__",
                False,
            )
        )
        self.assertTrue(
            getattr(
                launcher.app.write_csv,
                "__avachin_detection_report__",
                False,
            )
        )

    def test_attaches_contract_to_candidate_evidence(self) -> None:
        candidate = Candidate()
        detection = launcher.attach_detection_contract(
            source=Path("track.mp3"),
            audio=Audio(Tags()),
            candidate=candidate,
            config={"local_fingerprint_match_threshold": 86},
            min_confidence=85,
        )
        self.assertEqual(
            detection.decision,
            DetectionDecision.LOCAL_MATCH,
        )
        self.assertEqual(
            candidate.evidence["detection_decision"],
            "LOCAL_MATCH",
        )
        self.assertTrue(
            candidate.evidence["detection_safe_to_apply"]
        )
        json.dumps(candidate.evidence["detection_result"])

    def test_report_wrapper_preserves_legacy_csv_and_adds_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            source = report_dir / "track.mp3"
            candidate = Candidate()
            launcher.attach_detection_contract(
                source=source,
                audio=Audio(Tags()),
                candidate=candidate,
                config={"local_fingerprint_match_threshold": 86},
                min_confidence=85,
            )
            legacy_path = report_dir / "report.csv"

            def legacy_writer(path: Path, results: list[Any]) -> None:
                del results
                path.write_text("legacy\n", encoding="utf-8")

            with mock.patch.object(
                launcher,
                "_ORIGINAL_WRITE_CSV",
                legacy_writer,
            ):
                launcher._write_csv_with_detection_reports(
                    legacy_path,
                    [
                        RuntimeResult(
                            item_type="mp3",
                            source_path=str(source),
                            status="preview",
                        )
                    ],
                )

            self.assertEqual(
                legacy_path.read_text(encoding="utf-8"),
                "legacy\n",
            )
            self.assertTrue(
                (report_dir / "detection-report.json").is_file()
            )
            self.assertTrue(
                (report_dir / "detection-report.csv").is_file()
            )


if __name__ == "__main__":
    unittest.main()
