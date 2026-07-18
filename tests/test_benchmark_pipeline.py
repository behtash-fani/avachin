#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.avachin_operation import OperationEvent  # noqa: E402
from tools.benchmark_pipeline import run_pipeline  # noqa: E402


class FakeOperationRunner:
    def __init__(self, artifact_dir: Path, *, predicted_id: str = "rec-1", emit_artifact: bool = True):
        self.artifact_dir = artifact_dir
        self.predicted_id = predicted_id
        self.emit_artifact = emit_artifact
        self.request = None

    def run(self, request: Any, *, listener: Any = None, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self.request = request.normalized()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        detections = []
        for source in sorted(Path(self.request.root).rglob("*.mp3")):
            detections.append(
                {
                    "source_path": str(source.resolve()),
                    "title": "Song",
                    "artist": "Artist",
                    "decision": "LOCAL_MATCH",
                    "query_seconds": 0.025,
                    "confidence": {
                        "audio": 94,
                        "metadata": 94,
                        "identity": 94,
                        "overall": 94,
                    },
                    "evidence": {
                        "provider": "local_fingerprint",
                        "match_mode": "full",
                        "candidate_margin": 8,
                        "external_identifiers": {
                            "avachin_recording": self.predicted_id,
                        },
                    },
                }
            )
        detection_path = self.artifact_dir / "detection-report.json"
        detection_path.write_text(
            json.dumps({"schema_version": 1, "detections": detections}),
            encoding="utf-8",
        )
        (self.artifact_dir / "detection-report.csv").write_text(
            "source_path,decision\n",
            encoding="utf-8",
        )
        if listener is not None:
            listener(
                OperationEvent(
                    operation_id="test-operation",
                    sequence=1,
                    event_type="started",
                    operation="organizer-preview",
                    mode="preview",
                    status="running",
                )
            )
            if self.emit_artifact:
                listener(
                    OperationEvent(
                        operation_id="test-operation",
                        sequence=2,
                        event_type="artifact",
                        operation="organizer-preview",
                        mode="preview",
                        key="json_summary",
                        path=str(detection_path),
                    )
                )
            listener(
                OperationEvent(
                    operation_id="test-operation",
                    sequence=3,
                    event_type="completed",
                    operation="organizer-preview",
                    mode="preview",
                    status="completed",
                    exit_code=0,
                )
            )
        return {
            "operation_id": "test-operation",
            "operation": "organizer-preview",
            "status": "completed",
            "exit_code": 0,
            "duration_seconds": 0.05,
        }


class BenchmarkPipelineTests(unittest.TestCase):
    def write_manifest(self, root: Path) -> Path:
        reference = root / "references" / "local" / "source.mp3"
        reference.parent.mkdir(parents=True)
        reference.write_bytes(b"trusted source audio")
        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": "Pipeline fixture",
                    "seed": 42,
                    "references": [
                        {
                            "recording_id": "rec-1",
                            "path": "references/local/source.mp3",
                            "title": "Song",
                            "artist": "Artist",
                            "duration_seconds": 180,
                            "split": "validation",
                            "identifiers": {"avachin": "rec-1"},
                        }
                    ],
                    "transforms": [
                        {"transform_id": "clean", "kind": "identity"}
                    ],
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_full_pipeline_passes_offline_preview_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            manifest = self.write_manifest(corpus)
            runner = FakeOperationRunner(root / "operation-artifacts")
            result = run_pipeline(
                corpus_root=corpus,
                manifest_path=manifest,
                report_root=root / "reports",
                run_dir=root / "reports" / "run-test-pass",
                operation_runner=runner,
            )
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["benchmark_summary"]["gate_false_auto_apply_zero"])
            self.assertEqual(result["benchmark_summary"]["recall"], 1.0)
            self.assertIsNotNone(runner.request)
            self.assertEqual(runner.request.operation, "organizer-preview")
            self.assertEqual(runner.request.mode, "preview")
            self.assertTrue(runner.request.offline)
            run_dir = Path(result["run_dir"])
            for name in (
                "manifest.snapshot.json",
                "generated-manifest.json",
                "operation-events.jsonl",
                "detection-report.json",
                "benchmark-report.json",
                "benchmark-report.csv",
                "threshold-profile.json",
                "pipeline-report.json",
            ):
                self.assertTrue((run_dir / name).is_file(), name)
            pipeline = json.loads((run_dir / "pipeline-report.json").read_text(encoding="utf-8"))
            self.assertEqual(pipeline["status"], "passed")
            self.assertIn("pipeline_report", pipeline["artifacts"])

    def test_false_auto_apply_returns_gate_failed_but_keeps_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            manifest = self.write_manifest(corpus)
            runner = FakeOperationRunner(
                root / "operation-artifacts",
                predicted_id="wrong-recording",
            )
            result = run_pipeline(
                corpus_root=corpus,
                manifest_path=manifest,
                report_root=root / "reports",
                run_dir=root / "reports" / "run-test-fail",
                operation_runner=runner,
            )
            self.assertEqual(result["status"], "gate-failed")
            self.assertEqual(result["benchmark_summary"]["false_auto_apply"], 1)
            self.assertTrue(Path(result["artifacts"]["threshold_profile"]).is_file())
            best = result["calibration"]["profile"]
            self.assertGreater(best["detection_local_min_confidence"], 94)

    def test_missing_detection_artifact_fails_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus = root / "corpus"
            manifest = self.write_manifest(corpus)
            runner = FakeOperationRunner(
                root / "operation-artifacts",
                emit_artifact=False,
            )
            result = run_pipeline(
                corpus_root=corpus,
                manifest_path=manifest,
                report_root=root / "reports",
                run_dir=root / "reports" / "run-test-missing",
                operation_runner=runner,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("without a detection-report", result["error"])
            self.assertEqual(runner.request.mode, "preview")


if __name__ == "__main__":
    unittest.main()
