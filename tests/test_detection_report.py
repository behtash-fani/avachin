#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.detection_contract import (  # noqa: E402
    ConfidenceBreakdown,
    DetectionDecision,
    DetectionEvidence,
    DetectionResult,
)
from tools.detection_report import (  # noqa: E402
    canonical_source_key,
    write_detection_reports,
)


@dataclass
class RuntimeResult:
    item_type: str
    source_path: str
    status: str
    error: str | None = None


class DetectionReportTests(unittest.TestCase):
    def detection(self, source: str) -> DetectionResult:
        return DetectionResult(
            source_path=source,
            title="Pedar",
            artist="Shahrokh",
            album="",
            decision=DetectionDecision.LOCAL_MATCH,
            decision_reason="trusted-local-acoustic-identity",
            safe_to_apply=True,
            should_learn=False,
            confidence=ConfidenceBreakdown(
                97.0,
                100.0,
                99.0,
                98.1,
            ),
            evidence=DetectionEvidence(
                provider="local_fingerprint",
                match_mode="full",
                fingerprint_score=97.0,
                metadata_agreement={
                    "title": 100.0,
                    "artist": 100.0,
                    "duration": 100.0,
                },
                consensus_sources=("local_fingerprint",),
            ),
        )

    def test_writes_versioned_json_and_flat_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "track.mp3")
            detection = self.detection(source)
            json_path, csv_path, payload = write_detection_reports(
                Path(temp_dir),
                [RuntimeResult("mp3", source, "preview")],
                {
                    canonical_source_key(source): detection,
                },
                avachin_version="12.6",
            )
            self.assertEqual(
                payload["summary"]["LOCAL_MATCH"],
                1,
            )
            parsed = json.loads(
                json_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                parsed["detections"][0]["decision"],
                "LOCAL_MATCH",
            )
            with csv_path.open(
                encoding="utf-8-sig",
                newline="",
            ) as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(
                row["provider"],
                "local_fingerprint",
            )
            self.assertEqual(
                row["audio_confidence"],
                "97.0",
            )

    def test_read_error_becomes_reject_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = str(Path(temp_dir) / "broken.mp3")
            _, _, payload = write_detection_reports(
                Path(temp_dir),
                [
                    RuntimeResult(
                        "mp3",
                        source,
                        "skipped-read-error",
                        "decoder failed",
                    )
                ],
                {},
                avachin_version="12.6",
            )
            row = payload["detections"][0]
            self.assertEqual(row["decision"], "REJECT")
            self.assertEqual(
                row["runtime_error"],
                "decoder failed",
            )


if __name__ == "__main__":
    unittest.main()
