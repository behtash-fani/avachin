#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_contract import BenchmarkManifest, generated_samples  # noqa: E402
from tools.benchmark_metrics import evaluate_detections, summarize_rows  # noqa: E402


class BenchmarkMetricTests(unittest.TestCase):
    def manifest(self) -> BenchmarkManifest:
        return BenchmarkManifest.from_mapping(
            {
                "schema_version": 1,
                "name": "Metric test",
                "seed": 7,
                "references": [
                    {
                        "recording_id": "studio",
                        "path": "references/studio.mp3",
                        "title": "Pedar",
                        "artist": "Shahrokh",
                        "duration_seconds": 200,
                        "hard_negative_group": "pedar",
                        "identifiers": {"avachin": "101"},
                    },
                    {
                        "recording_id": "live",
                        "path": "references/live.mp3",
                        "title": "Pedar",
                        "artist": "Shahrokh",
                        "duration_seconds": 230,
                        "version": "live",
                        "hard_negative_group": "pedar",
                        "identifiers": {"avachin": "102"},
                    },
                ],
                "transforms": [
                    {"transform_id": "clean", "kind": "identity"}
                ],
            }
        )

    def detection(
        self,
        source: Path,
        recording_id: str | None,
        *,
        decision: str = "LOCAL_MATCH",
        query_seconds: float = 0.1,
    ) -> dict[str, object]:
        external = (
            {"avachin_recording": recording_id}
            if recording_id is not None
            else {}
        )
        return {
            "source_path": str(source),
            "title": "Pedar",
            "artist": "Shahrokh",
            "decision": decision,
            "query_seconds": query_seconds,
            "confidence": {
                "audio": 97,
                "metadata": 95,
                "identity": 98,
                "overall": 97,
            },
            "evidence": {
                "provider": "local_fingerprint",
                "match_mode": "full",
                "candidate_margin": 8,
                "external_identifiers": external,
            },
        }

    def test_false_auto_apply_and_precision_are_measured(self) -> None:
        manifest = self.manifest()
        samples = generated_samples(manifest)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            studio = next(item for item in samples if item.expected_recording_id == "studio")
            live = next(item for item in samples if item.expected_recording_id == "live")
            report = {
                "detections": [
                    self.detection(root / studio.path, "101", query_seconds=0.1),
                    self.detection(root / live.path, "101", query_seconds=0.3),
                ]
            }
            rows = evaluate_detections(
                manifest=manifest,
                samples=samples,
                detection_report=report,
                corpus_root=root,
            )
        summary = summarize_rows(rows)
        self.assertEqual(summary["true_positive"], 1)
        self.assertEqual(summary["false_positive"], 1)
        self.assertEqual(summary["precision"], 0.5)
        self.assertEqual(summary["recall"], 0.5)
        self.assertEqual(summary["false_auto_apply"], 1)
        self.assertFalse(summary["gate_false_auto_apply_zero"])
        self.assertEqual(summary["query_seconds_p50"], 0.2)

    def test_ambiguous_text_only_does_not_pass_hard_negative_identity(self) -> None:
        manifest = self.manifest()
        samples = generated_samples(manifest)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = {
                "detections": [
                    self.detection(root / sample.path, None)
                    for sample in samples
                ]
            }
            rows = evaluate_detections(
                manifest=manifest,
                samples=samples,
                detection_report=report,
                corpus_root=root,
            )
        self.assertTrue(all(not row.correct for row in rows))
        self.assertTrue(all(row.false_auto_apply for row in rows))

    def test_review_result_is_not_an_auto_apply(self) -> None:
        manifest = self.manifest()
        samples = generated_samples(manifest)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample = samples[0]
            report = {
                "detections": [
                    self.detection(
                        root / sample.path,
                        "101",
                        decision="REVIEW",
                    )
                ]
            }
            rows = evaluate_detections(
                manifest=manifest,
                samples=[sample],
                detection_report=report,
                corpus_root=root,
            )
        self.assertTrue(rows[0].correct)
        self.assertFalse(rows[0].auto_apply)
        self.assertFalse(rows[0].false_auto_apply)


if __name__ == "__main__":
    unittest.main()
