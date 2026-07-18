#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.identity_resolver import resolve_candidate  # noqa: E402


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
            "local_fingerprint_recording_id": "rec_123",
            "local_fingerprint_match_mode": "full",
        }
    )
    isrc: str | None = None
    musicbrainz_recording_id: str | None = None
    spotify_track_id: str | None = None
    apple_track_id: str | None = None


class BenchmarkDetectionIdentityTests(unittest.TestCase):
    def test_local_recording_id_is_exposed_as_stable_identity(self) -> None:
        result = resolve_candidate(
            source_path=Path("track.mp3"),
            audio=Audio(),
            candidate=Candidate(),
            config={"local_fingerprint_match_threshold": 86},
            min_confidence=85,
        )
        self.assertEqual(
            result.evidence.external_identifiers["avachin_recording"],
            "rec_123",
        )
        self.assertEqual(result.decision.value, "LOCAL_MATCH")


if __name__ == "__main__":
    unittest.main()
