#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_contract import BenchmarkManifest, generated_samples  # noqa: E402
from tools.benchmark_review import (  # noqa: E402
    load_review,
    quarantine_reference,
    reanalyze_run,
    restore_reference,
)


class BenchmarkReviewTests(unittest.TestCase):
    def manifest_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "name": "review workflow",
            "seed": 17,
            "references": [
                {
                    "recording_id": "good",
                    "path": "references/good.mp3",
                    "title": "Good Song",
                    "artist": "Good Artist",
                    "duration_seconds": 180,
                    "split": "validation",
                    "identifiers": {"avachin": "good"},
                },
                {
                    "recording_id": "bad",
                    "path": "references/bad.mp3",
                    "title": "Wrong Label",
                    "artist": "Wrong Artist",
                    "duration_seconds": 180,
                    "split": "validation",
                    "identifiers": {"avachin": "bad"},
                },
            ],
            "transforms": [{"transform_id": "clean", "kind": "identity"}],
        }

    def write_run(self, root: Path) -> tuple[Path, Path, Path]:
        corpus = root / "benchmark"
        run_dir = root / "reports" / "benchmark" / "run-test"
        run_dir.mkdir(parents=True)
        manifest_payload = self.manifest_payload()
        manifest_path = corpus / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "manifest.snapshot.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest = BenchmarkManifest.from_mapping(manifest_payload)
        samples = generated_samples(manifest, generated_root="generated/run-test")
        (run_dir / "generated-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "samples": [sample.to_dict() for sample in samples],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        detections = []
        for sample in samples:
            expected = sample.expected_recording_id
            predicted = "good" if expected == "good" else "other-recording"
            detections.append(
                {
                    "source_path": str((corpus / sample.path).resolve()),
                    "title": "Good Song" if expected == "good" else "Actual Song",
                    "artist": "Good Artist" if expected == "good" else "Actual Artist",
                    "decision": "LOCAL_MATCH",
                    "query_seconds": 0.05,
                    "confidence": {
                        "audio": 99,
                        "metadata": 99,
                        "identity": 99,
                        "overall": 99,
                    },
                    "evidence": {
                        "provider": "local_fingerprint",
                        "match_mode": "full",
                        "candidate_margin": 10,
                        "external_identifiers": {
                            "avachin_recording": predicted,
                        },
                    },
                }
            )
        (run_dir / "detection-report.json").write_text(
            json.dumps({"detections": detections}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "pipeline-report.json").write_text(
            json.dumps({"corpus_root": str(corpus.resolve())}),
            encoding="utf-8",
        )
        return corpus, run_dir, manifest_path

    def test_quarantine_records_confirmation_and_restore_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus, _, manifest_path = self.write_run(Path(temp_dir))
            review_path = corpus / "review.json"
            result = quarantine_reference(
                manifest_path=manifest_path,
                review_path=review_path,
                recording_id="bad",
                reason="file audio was manually confirmed to be another song",
                confirmed_artist="Actual Artist",
                confirmed_title="Actual Song",
                confirmed_by="benchmark owner",
            )
            self.assertEqual(result["status"], "quarantined")
            review = load_review(review_path)
            self.assertEqual(
                review["references"]["bad"]["manifest_title"],
                "Wrong Label",
            )
            self.assertEqual(
                review["references"]["bad"]["confirmed_title"],
                "Actual Song",
            )
            restored = restore_reference(
                review_path=review_path,
                recording_id="bad",
            )
            self.assertTrue(restored["restored"])
            self.assertNotIn("bad", load_review(review_path)["references"])

    def test_reanalyze_uses_saved_detection_and_excludes_confirmed_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus, run_dir, manifest_path = self.write_run(Path(temp_dir))
            review_path = corpus / "review.json"

            failed = reanalyze_run(
                run_dir=run_dir,
                corpus_root=corpus,
                review_path=review_path,
            )
            self.assertEqual(failed["status"], "gate-failed")
            self.assertEqual(failed["benchmark_summary"]["false_auto_apply"], 1)

            quarantine_reference(
                manifest_path=manifest_path,
                review_path=review_path,
                recording_id="bad",
                reason="confirmed mislabeled reference",
                confirmed_artist="Actual Artist",
                confirmed_title="Actual Song",
            )
            passed = reanalyze_run(
                run_dir=run_dir,
                corpus_root=corpus,
                review_path=review_path,
            )
            self.assertEqual(passed["status"], "passed")
            self.assertEqual(passed["benchmark_summary"]["total"], 1)
            self.assertEqual(passed["benchmark_summary"]["false_auto_apply"], 0)
            self.assertEqual(passed["review"]["quarantined_recording_count"], 1)
            self.assertEqual(passed["review"]["quarantined_sample_count"], 1)
            for name in (
                "benchmark-reviewed-report.json",
                "benchmark-reviewed-report.csv",
                "threshold-reviewed-profile.json",
                "pipeline-reviewed-report.json",
            ):
                self.assertTrue((run_dir / name).is_file(), name)

    def test_unknown_recording_cannot_be_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus, _, manifest_path = self.write_run(Path(temp_dir))
            with self.assertRaises(ValueError):
                quarantine_reference(
                    manifest_path=manifest_path,
                    review_path=corpus / "review.json",
                    recording_id="missing",
                    reason="invalid",
                )


if __name__ == "__main__":
    unittest.main()
