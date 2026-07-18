#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned, JSON-safe detection result contract for Avachin."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

DETECTION_SCHEMA_VERSION = 1


class DetectionDecision(str, Enum):
    LOCAL_MATCH = "LOCAL_MATCH"
    AUTO_LEARN = "AUTO_LEARN"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class ConfidenceBreakdown:
    audio: float | None
    metadata: float
    identity: float
    overall: float

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


@dataclass(frozen=True)
class DetectionEvidence:
    provider: str
    match_mode: str = ""
    fingerprint_score: float | None = None
    segment_coverage: float | None = None
    offset_seconds: float | None = None
    candidate_margin: float | None = None
    metadata_agreement: dict[str, float] = field(default_factory=dict)
    consensus_sources: tuple[str, ...] = ()
    external_identifiers: dict[str, str] = field(default_factory=dict)
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["consensus_sources"] = list(self.consensus_sources)
        payload["flags"] = list(self.flags)
        return {
            key: value
            for key, value in payload.items()
            if value not in ("", None, [], {}, ())
        }


@dataclass(frozen=True)
class DetectionResult:
    source_path: str
    title: str
    artist: str
    album: str
    decision: DetectionDecision
    decision_reason: str
    safe_to_apply: bool
    should_learn: bool
    confidence: ConfidenceBreakdown
    evidence: DetectionEvidence
    schema_version: int = DETECTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "decision": self.decision.value,
            "decision_reason": self.decision_reason,
            "safe_to_apply": self.safe_to_apply,
            "should_learn": self.should_learn,
            "confidence": self.confidence.to_dict(),
            "evidence": self.evidence.to_dict(),
        }
