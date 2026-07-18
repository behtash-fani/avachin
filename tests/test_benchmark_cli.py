#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_benchmark as benchmark  # noqa: E402


class BenchmarkCliTests(unittest.TestCase):
    def write_manifest(self, root: Path) -> Path:
        path = root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "CLI test",
                    "seed": 123,
                    "references": [
                        {
                            "recording_id": "song-1",
                            "path": "references/song.mp3",
                            "title": "Song",
                            "artist": "Artist",
                            "duration_seconds": 180,
                            "identifiers": {"avachin": "1"},
                        }
                    ],
                    "transforms": [
                        {"transform_id": "clean", "kind": "identity"},
                        {
                            "transform_id": "clip-10",
                            "kind": "clip",
                            "parameters": {
                                "duration_seconds": 10,
                                "position": "middle",
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_validate_and_plan_without_audio_or_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = self.write_manifest(root)
            validated = benchmark.command_validate(Namespace(manifest=str(manifest)))
            self.assertEqual(validated["planned_samples"], 2)
            generated = root / "generated-manifest.json"
            result = benchmark.command_generate(
                Namespace(
                    manifest=str(manifest),
                    corpus_root=str(root),
                    generated_root="generated",
                    output_manifest=str(generated),
                    ffmpeg=None,
                    plan_only=True,
                )
            )
            self.assertEqual(result["status"], "planned")
            payload = json.loads(generated.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["samples"]), 2)

    def test_evaluate_writes_official_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = self.write_manifest(root)
            generated = root / "generated-manifest.json"
            benchmark.command_generate(
                Namespace(
                    manifest=str(manifest),
                    corpus_root=str(root),
                    generated_root="generated",
                    output_manifest=str(generated),
                    ffmpeg=None,
                    plan_only=True,
                )
            )
            generated_payload = json.loads(generated.read_text(encoding="utf-8"))
            detections = []
            for sample in generated_payload["samples"]:
                detections.append(
                    {
                        "source_path": str(root / sample["path"]),
                        "title": "Song",
                        "artist": "Artist",
                        "decision": "LOCAL_MATCH",
                        "confidence": {
                            "audio": 98,
                            "metadata": 98,
                            "identity": 99,
                            "overall": 98.5,
                        },
                        "evidence": {
                            "provider": "local_fingerprint",
                            "match_mode": "full",
                            "candidate_margin": 8,
                            "external_identifiers": {
                                "avachin_recording": "1"
                            },
                        },
                    }
                )
            detection_report = root / "detection-report.json"
            detection_report.write_text(
                json.dumps({"detections": detections}),
                encoding="utf-8",
            )
            report_dir = root / "reports"
            result = benchmark.command_evaluate(
                Namespace(
                    manifest=str(manifest),
                    generated_manifest=str(generated),
                    detection_report=str(detection_report),
                    corpus_root=str(root),
                    config=None,
                    report_dir=str(report_dir),
                )
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["summary"]["false_auto_apply"], 0)
            self.assertEqual(result["summary"]["recall"], 1.0)
            self.assertTrue((report_dir / "benchmark-report.json").is_file())
            self.assertTrue((report_dir / "benchmark-report.csv").is_file())


if __name__ == "__main__":
    unittest.main()
