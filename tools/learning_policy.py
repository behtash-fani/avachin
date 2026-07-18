#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative four-way decision policy for Avachin detections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from tools.detection_contract import (
    ConfidenceBreakdown,
    DetectionDecision,
    DetectionEvidence,
)

ONLINE_SOURCES = {
    "acoustid",
    "audd",
    "musicbrainz",
    "apple",
    "spotify",
    "deezer",
}


@dataclass(frozen=True)
class DecisionOutcome:
    decision: DetectionDecision
    reason: str

    @property
    def safe_to_apply(self) -> bool:
        return self.decision in {
            DetectionDecision.LOCAL_MATCH,
            DetectionDecision.AUTO_LEARN,
        }

    @property
    def should_learn(self) -> bool:
        return self.decision is DetectionDecision.AUTO_LEARN


def _number(
    config: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def decide(
    *,
    provider: str,
    valid_identity: bool,
    input_identity_reliable: bool,
    confidence: ConfidenceBreakdown,
    evidence: DetectionEvidence,
    runtime_evidence: Mapping[str, Any],
    config: Mapping[str, Any],
    min_confidence: float,
) -> DecisionOutcome:
    source = str(provider or "").casefold()
    if not valid_identity or source == "unknown-fallback":
        return DecisionOutcome(
            DetectionDecision.REJECT,
            "identity-is-missing-or-placeholder",
        )

    review_min = _number(
        config,
        "detection_review_min_confidence",
        70.0,
    )
    local_min = max(
        float(min_confidence),
        _number(config, "detection_local_min_confidence", 86.0),
    )

    if source == "local_fingerprint":
        acoustic_min = _number(
            config,
            "local_fingerprint_match_threshold",
            _number(
                config,
                "detection_local_audio_min_confidence",
                86.0,
            ),
        )
        if confidence.audio is None or confidence.audio < acoustic_min:
            return DecisionOutcome(
                DetectionDecision.REVIEW,
                "local-audio-confidence-below-threshold",
            )
        if evidence.match_mode == "segment":
            margin_min = _number(
                config,
                "local_fingerprint_partial_min_margin",
                _number(config, "detection_partial_min_margin", 2.0),
            )
            if (
                evidence.candidate_margin is None
                or evidence.candidate_margin < margin_min
            ):
                return DecisionOutcome(
                    DetectionDecision.REVIEW,
                    "partial-candidate-margin-below-threshold",
                )
        if confidence.identity >= local_min:
            return DecisionOutcome(
                DetectionDecision.LOCAL_MATCH,
                "trusted-local-acoustic-identity",
            )
        return DecisionOutcome(
            DetectionDecision.REVIEW,
            "local-identity-confidence-below-threshold",
        )

    if source == "existing-tags":
        if (
            input_identity_reliable
            and confidence.metadata >= local_min
            and confidence.identity >= local_min
        ):
            return DecisionOutcome(
                DetectionDecision.LOCAL_MATCH,
                "trusted-existing-local-identity",
            )
        return DecisionOutcome(
            DetectionDecision.REVIEW,
            "existing-tags-require-review",
        )

    if source == "local-registry":
        registry_min = max(
            local_min,
            _number(config, "registry_confidence", 91.0),
        )
        if (
            confidence.identity >= registry_min
            and confidence.metadata >= 85.0
        ):
            return DecisionOutcome(
                DetectionDecision.LOCAL_MATCH,
                "trusted-local-registry-identity",
            )
        return DecisionOutcome(
            DetectionDecision.REVIEW,
            "local-registry-below-threshold",
        )

    if source in ONLINE_SOURCES:
        learn_status = str(
            runtime_evidence.get("online_auto_learn_status") or ""
        ).casefold()
        learn_reason = str(
            runtime_evidence.get("online_auto_learn_reason") or ""
        ).casefold()
        if learn_status == "learned":
            return DecisionOutcome(
                DetectionDecision.AUTO_LEARN,
                "trusted-online-identity-learned-locally",
            )
        if (
            learn_reason == "input-identity-already-reliable"
            and input_identity_reliable
            and confidence.metadata >= 92.0
            and confidence.identity >= local_min
        ):
            return DecisionOutcome(
                DetectionDecision.LOCAL_MATCH,
                "trusted-local-identity-with-online-enrichment",
            )
        if confidence.overall >= review_min:
            return DecisionOutcome(
                DetectionDecision.REVIEW,
                f"online-result-not-learned:{learn_status or 'unknown'}",
            )
        return DecisionOutcome(
            DetectionDecision.REJECT,
            "online-result-below-review-threshold",
        )

    if confidence.overall >= review_min:
        return DecisionOutcome(
            DetectionDecision.REVIEW,
            "untrusted-source-requires-review",
        )
    return DecisionOutcome(
        DetectionDecision.REJECT,
        "confidence-below-review-threshold",
    )
