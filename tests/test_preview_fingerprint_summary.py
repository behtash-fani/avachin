#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from tools import summarize_preview_fingerprints as summary


class PreviewFingerprintSummaryTests(unittest.TestCase):
    def write_report(self, root: Path) -> Path:
        report_dir = root / "20260718_010003_161978"
        report_dir.mkdir(parents=True)
        report = report_dir / "report.csv"
        fields = [
            "item_type",
            "source_path",
            "old_filename",
            "new_filename",
            "status",
            "match_source",
            "confidence",
            "title",
            "artist",
            "album",
            "final_path",
        ]
        rows = [
            {
                "item_type": "mp3",
                "source_path": r"C:\Music\_Unknown Artist\Untitled - Unknown Artist.mp3",
                "old_filename": "Untitled - Unknown Artist.mp3",
                "new_filename": "Baazi - Siavash Ghomayshi.mp3",
                "status": "preview",
                "match_source": "local_fingerprint",
                "confidence": "91.25",
                "title": "Baazi",
                "artist": "Siavash Ghomayshi",
                "album": "Baazi",
                "final_path": r"C:\Music\Siavash Ghomayshi\Baazi\Baazi - Siavash Ghomayshi.mp3",
            },
            {
                "item_type": "mp3",
                "source_path": r"C:\Music\Faded.mp3",
                "old_filename": "Faded.mp3",
                "new_filename": "Faded - Alan Walker.mp3",
                "status": "preview",
                "match_source": "musicbrainz",
                "confidence": "100",
                "title": "Faded",
                "artist": "Alan Walker",
                "album": "Different World",
                "final_path": r"C:\Music\Alan Walker\Different World\Faded - Alan Walker.mp3",
            },
        ]
        with report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return report

    def test_latest_report_and_local_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = self.write_report(root)
            self.assertEqual(summary.latest_report(root), report)
            rows = summary.read_rows(report)
            local = summary.filter_rows(rows, source="local_fingerprint")
            self.assertEqual(len(local), 1)
            self.assertEqual(local[0]["title"], "Baazi")

    def test_contains_searches_source_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = self.write_report(Path(temp_dir))
            rows = summary.read_rows(report)
            self.assertEqual(len(summary.filter_rows(rows, contains="unknown artist")), 1)
            self.assertEqual(len(summary.filter_rows(rows, contains="siavash ghomayshi")), 1)
            self.assertEqual(len(summary.filter_rows(rows, contains="not-present")), 0)


if __name__ == "__main__":
    unittest.main()
