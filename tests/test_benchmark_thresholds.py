#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_metrics import EvaluationRow  # noqa: E402
from tools.benchmark_thresholds import (  # noqa: E402
    ThresholdProfile,
    calibrate,
    classify,
)


class BenchmarkThresholdTests(unittest.TestCase):
    def row(
        self,
        sample_id: str,
        *,
        correct: bool,
        match_mode: str = "full",
        identity: float = 95,
        audio: float | None = 95,
        metadata: float = 95,
        overall: float = 95,
        margin: float | None = 8,
    ) -> EvaluationRow:
        return EvaluationRow(
            sample_id=sample_id,
            expected_recording_id="expected",
            predicted_recording_id="expected" if correct else "wrong",
            transform_id="clean",
            transform_kind="identity",
            split="validation",
            version="studio",
            hard_negative_group="",
            decision="LOCAL_MATCH",
            provider="local_fingerprint",
            match_mode=match_mode,
            correct=correct,
            identified=True,
            auto_apply=True,
            false_auto_apply=not correct,
            audio_confidence=audio,
            metadata_confidence=metadata,
            identity_confidence=identity,
            overall_confidence=overall,
            candidate_margin=margin,
            query_seconds=0.1,
            expected_identity_keys=("avachin:1",),
            predicted_identity_keys=("avachin:1" if correct else "avachin:2",),
        )

    def test_segment_without_margin_cannot_auto_apply(self) -> None:
        profile = ThresholdProfile(90, 90, 90, 2, 70)
        row = self.row(
            "partial",
            correct=True,
            match_mode="segment",
            margin=None,
        )
        self.assertEqual(classify(row, profile), "REVIEW")

    def test_calibration_selects_zero_false_auto_apply_profile(self) -> None:
        rows = [
            self.row("correct-full", correct=True),
            self.row(
                "wrong-partial",
                correct=False,
                match_mode="segment",
                margin=1,
                identity=96,
                audio=96,
                metadata=96,
                overall=96,
            ),
        ]
        best, safe = calibrate(
            rows,
            identity_values=[90],
            audio_values=[90],
            metadata_values=[90],
            margin_values=[0, 2],
            review_values=[70],
        )
        self.assertEqual(best.false_auto_apply, 0)
        self.assertEqual(best.correct_auto_apply, 1)
        self.assertEqual(best.profile.partial_margin_min, 2)
        self.assertTrue(all(item.false_auto_apply == 0 for item in safe))

    def test_missing_audio_is_allowed_for_strong_metadata_identity(self) -> None:
        profile = ThresholdProfile(90, 95, 90, 2, 70)
        row = self.row(
            "metadata",
            correct=True,
            audio=None,
            identity=96,
            metadata=96,
        )
        self.assertEqual(classify(row, profile), "AUTO_APPLY")


if __name__ == "__main__":
    unittest.main()
