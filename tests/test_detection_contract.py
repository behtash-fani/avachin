#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.confidence import acoustic_score  # noqa: E402
from tools.detection_contract import DetectionDecision  # noqa: E402
from tools.identity_resolver import resolve_candidate  # noqa: E402


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
    source: str
    title: str = "Pedar"
    artist: str = "Shahrokh"
    album: str = ""
    confidence: float = 99.0
    title_similarity: float = 100.0
    artist_similarity: float = 100.0
    duration_similarity: float = 100.0
    duration_ms: int = 200000
    consensus_sources: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    isrc: str | None = None
    musicbrainz_recording_id: str | None = None
    spotify_track_id: str | None = None
    apple_track_id: str | None = None


class DetectionContractTests(unittest.TestCase):
    def resolve(
        self,
        candidate: Candidate,
        tags: Tags | None = None,
    ):
        return resolve_candidate(
            source_path="track.mp3",
            audio=Audio(tags or Tags()),
            candidate=candidate,
            config={
                "local_fingerprint_match_threshold": 86,
                "local_fingerprint_partial_min_margin": 2,
            },
            min_confidence=85,
        )

    def test_fractional_acoustic_score_is_normalized(self) -> None:
        self.assertEqual(acoustic_score(0.94), 94.0)
        self.assertEqual(acoustic_score(94), 94.0)

    def test_full_local_fingerprint_is_local_match(self) -> None:
        result = self.resolve(
            Candidate(
                source="local_fingerprint",
                evidence={
                    "local_fingerprint_score": 0.97,
                    "local_first": True,
                },
                consensus_sources=["local_fingerprint"],
            )
        )
        self.assertEqual(
            result.decision,
            DetectionDecision.LOCAL_MATCH,
        )
        self.assertTrue(result.safe_to_apply)
        self.assertEqual(result.confidence.audio, 97.0)
        json.dumps(result.to_dict())

    def test_partial_low_margin_requires_review(self) -> None:
        result = self.resolve(
            Candidate(
                source="local_fingerprint",
                evidence={
                    "local_fingerprint_score": 96,
                    "local_fingerprint_match_mode": "segment",
                    "local_fingerprint_runner_up_margin": 1.5,
                    "local_fingerprint_segment_start_seconds": 30,
                    "local_fingerprint_segment_end_seconds": 45,
                    "partial_audio_match": True,
                },
            )
        )
        self.assertEqual(
            result.decision,
            DetectionDecision.REVIEW,
        )
        self.assertEqual(
            result.decision_reason,
            "partial-candidate-margin-below-threshold",
        )

    def test_online_learned_is_auto_learn(self) -> None:
        result = self.resolve(
            Candidate(
                source="audd",
                confidence=96,
                evidence={
                    "audd_provider": True,
                    "online_auto_learn_status": "learned",
                    "exact_isrc": True,
                },
                isrc="IR-AAA-26-00001",
            )
        )
        self.assertEqual(
            result.decision,
            DetectionDecision.AUTO_LEARN,
        )
        self.assertTrue(result.should_learn)

    def test_reliable_local_identity_with_online_enrichment_is_local_match(
        self,
    ) -> None:
        result = self.resolve(
            Candidate(
                source="musicbrainz",
                confidence=97,
                evidence={
                    "online_auto_learn_status": "skipped",
                    "online_auto_learn_reason": (
                        "input-identity-already-reliable"
                    ),
                },
            ),
            Tags(title="Pedar", artist="Shahrokh"),
        )
        self.assertEqual(
            result.decision,
            DetectionDecision.LOCAL_MATCH,
        )

    def test_unknown_fallback_is_rejected(self) -> None:
        result = self.resolve(
            Candidate(
                source="unknown-fallback",
                title="Untitled",
                artist="Unknown Artist",
                confidence=25,
                title_similarity=0,
                artist_similarity=0,
            )
        )
        self.assertEqual(
            result.decision,
            DetectionDecision.REJECT,
        )
        self.assertFalse(result.safe_to_apply)


if __name__ == "__main__":
    unittest.main()
