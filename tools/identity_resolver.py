#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adapt the legacy Candidate object to the stable DetectionResult contract."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping

from tools.confidence import (
    acoustic_score,
    confidence_breakdown,
    identity_confidence,
    metadata_confidence,
)
from tools.detection_contract import DetectionEvidence, DetectionResult
from tools.learning_policy import decide

PLACEHOLDERS = {
    "",
    "-",
    "na",
    "n/a",
    "none",
    "unknown",
    "unknown artist",
    "unknown title",
    "untitled",
    "no title",
    "track",
    "track 1",
}
SOURCE_QUALITY = {
    "local_fingerprint": 99.0,
    "audd": 96.0,
    "acoustid": 94.0,
    "musicbrainz": 91.0,
    "spotify": 95.0,
    "apple": 88.0,
    "local-registry": 91.0,
    "existing-tags": 90.0,
    "local-cleanup": 65.0,
    "unknown-fallback": 20.0,
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _key(value: Any) -> str:
    return _text(value).casefold()


def _placeholder(value: Any) -> bool:
    text = _key(value)
    return text in PLACEHOLDERS or any(
        marker in text
        for marker in (
            "unknown artist",
            "unknown title",
            "untitled",
        )
    )


def _similarity(left: Any, right: Any) -> float:
    left_key = re.sub(r"\s+", " ", _key(left))
    right_key = re.sub(r"\s+", " ", _key(right))
    if not left_key or not right_key:
        return 0.0
    return round(
        100.0 * SequenceMatcher(None, left_key, right_key).ratio(),
        2,
    )


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _candidate_score(
    candidate: Any,
    attribute: str,
    fallback: float,
) -> float:
    value = _float(getattr(candidate, attribute, None))
    if value is None or value <= 0:
        return fallback
    return max(0.0, min(100.0, value))


def _duration_agreement(audio: Any, candidate: Any) -> float:
    local_seconds = _float(getattr(audio, "duration_seconds", None))
    candidate_ms = _float(getattr(candidate, "duration_ms", None))
    if not local_seconds or not candidate_ms:
        return _candidate_score(
            candidate,
            "duration_similarity",
            55.0,
        )
    difference = abs(local_seconds - candidate_ms / 1000.0)
    if difference <= 1.5:
        return 100.0
    if difference <= 3:
        return 96.0
    if difference <= 5:
        return 90.0
    if difference <= 8:
        return 80.0
    if difference <= 12:
        return 65.0
    if difference <= 20:
        return 40.0
    return 0.0


def _runtime_evidence(candidate: Any) -> dict[str, Any]:
    value = getattr(candidate, "evidence", None)
    return dict(value) if isinstance(value, dict) else {}


def _audio_score(
    provider: str,
    candidate: Any,
    evidence: Mapping[str, Any],
) -> float | None:
    for key in (
        "local_fingerprint_score",
        "fingerprint_score",
        "acoustid_score",
        "audd_score",
    ):
        score = acoustic_score(evidence.get(key))
        if score is not None:
            return score
    if provider == "audd" or bool(evidence.get("audd_provider")):
        return acoustic_score(getattr(candidate, "confidence", None))
    return None


def _match_mode(
    provider: str,
    evidence: Mapping[str, Any],
) -> str:
    explicit = _text(evidence.get("local_fingerprint_match_mode"))
    if explicit:
        return explicit.casefold()
    if provider == "local_fingerprint":
        return "segment" if evidence.get("partial_audio_match") else "full"
    if provider in {"acoustid", "audd"}:
        return "acoustic"
    return "metadata"


def _segment_coverage(
    candidate: Any,
    evidence: Mapping[str, Any],
) -> float | None:
    explicit = _float(
        evidence.get("local_fingerprint_segment_coverage")
    )
    if explicit is not None:
        if 0 <= explicit <= 1:
            explicit *= 100.0
        return max(0.0, min(100.0, explicit))

    start = _float(
        evidence.get("local_fingerprint_segment_start_seconds")
    )
    end = _float(
        evidence.get("local_fingerprint_segment_end_seconds")
    )
    duration_ms = _float(getattr(candidate, "duration_ms", None))
    if (
        start is None
        or end is None
        or end <= start
        or not duration_ms
    ):
        return None
    return round(
        max(
            0.0,
            min(
                100.0,
                (end - start) / (duration_ms / 1000.0) * 100.0,
            ),
        ),
        2,
    )


def _external_ids(
    candidate: Any,
    runtime_evidence: Mapping[str, Any],
) -> dict[str, str]:
    avachin_recording = (
        runtime_evidence.get("local_fingerprint_recording_id")
        or runtime_evidence.get("online_auto_learn_recording_id")
    )
    values = {
        "avachin_recording": avachin_recording,
        "isrc": getattr(candidate, "isrc", None),
        "musicbrainz_recording": getattr(
            candidate,
            "musicbrainz_recording_id",
            None,
        ),
        "spotify_track": getattr(candidate, "spotify_track_id", None),
        "apple_track": getattr(candidate, "apple_track_id", None),
    }
    return {
        key: _text(value)
        for key, value in values.items()
        if _text(value)
    }


def resolve_candidate(
    *,
    source_path: str | Path,
    audio: Any,
    candidate: Any,
    config: Mapping[str, Any],
    min_confidence: float,
) -> DetectionResult:
    provider = _key(getattr(candidate, "source", ""))
    runtime_evidence = _runtime_evidence(candidate)
    tags = getattr(audio, "tags", None)
    tag_title = getattr(tags, "title", "") if tags is not None else ""
    tag_artist = ""
    if tags is not None:
        tag_artist = (
            getattr(tags, "artist", "")
            or getattr(tags, "albumartist", "")
        )
    input_identity_reliable = (
        not _placeholder(tag_title)
        and not _placeholder(tag_artist)
    )

    title_agreement = _candidate_score(
        candidate,
        "title_similarity",
        _similarity(getattr(candidate, "title", ""), tag_title),
    )
    artist_agreement = _candidate_score(
        candidate,
        "artist_similarity",
        _similarity(getattr(candidate, "artist", ""), tag_artist),
    )
    duration_agreement = _duration_agreement(audio, candidate)
    exact_identifier = bool(
        runtime_evidence.get("exact_isrc")
        or getattr(candidate, "musicbrainz_recording_id", None)
    )
    metadata = metadata_confidence(
        title=title_agreement,
        artist=artist_agreement,
        duration=duration_agreement,
        exact_identifier=exact_identifier,
    )
    audio_score = _audio_score(
        provider,
        candidate,
        runtime_evidence,
    )
    identity = identity_confidence(
        candidate_confidence=getattr(candidate, "confidence", 0.0),
        metadata=metadata,
        source_quality=SOURCE_QUALITY.get(provider, 70.0),
        exact_identifier=exact_identifier,
    )
    breakdown = confidence_breakdown(
        audio=audio_score,
        metadata=metadata,
        identity=identity,
    )

    match_mode = _match_mode(provider, runtime_evidence)
    offset = _float(
        runtime_evidence.get(
            "local_fingerprint_segment_start_seconds"
        )
    )
    margin_value = runtime_evidence.get(
        "local_fingerprint_runner_up_margin"
    )
    if margin_value is None:
        margin_value = runtime_evidence.get("candidate_margin")
    margin = _float(margin_value)
    consensus = tuple(
        sorted(
            {
                _key(value)
                for value in (
                    getattr(candidate, "consensus_sources", None)
                    or []
                )
                if _key(value)
            }
        )
    )

    flags: list[str] = []
    for key in (
        "local_first",
        "local_first_offline",
        "online_lookup_skipped",
        "partial_audio_match",
        "exact_isrc",
    ):
        if runtime_evidence.get(key):
            flags.append(key)
    if input_identity_reliable:
        flags.append("input_identity_reliable")
    learn_status = _key(
        runtime_evidence.get("online_auto_learn_status")
    )
    if learn_status:
        flags.append(f"online_auto_learn:{learn_status}")

    evidence = DetectionEvidence(
        provider=provider,
        match_mode=match_mode,
        fingerprint_score=audio_score,
        segment_coverage=_segment_coverage(
            candidate,
            runtime_evidence,
        ),
        offset_seconds=offset,
        candidate_margin=margin,
        metadata_agreement={
            "title": round(title_agreement, 2),
            "artist": round(artist_agreement, 2),
            "duration": round(duration_agreement, 2),
        },
        consensus_sources=consensus,
        external_identifiers=_external_ids(candidate, runtime_evidence),
        flags=tuple(flags),
    )
    valid_identity = bool(
        _text(getattr(candidate, "title", ""))
        and _text(getattr(candidate, "artist", ""))
        and not _placeholder(getattr(candidate, "title", ""))
        and not _placeholder(getattr(candidate, "artist", ""))
    )
    outcome = decide(
        provider=provider,
        valid_identity=valid_identity,
        input_identity_reliable=input_identity_reliable,
        confidence=breakdown,
        evidence=evidence,
        runtime_evidence=runtime_evidence,
        config=config,
        min_confidence=min_confidence,
    )
    return DetectionResult(
        source_path=str(Path(source_path)),
        title=_text(getattr(candidate, "title", "")),
        artist=_text(getattr(candidate, "artist", "")),
        album=_text(getattr(candidate, "album", "")),
        decision=outcome.decision,
        decision_reason=outcome.reason,
        safe_to_apply=outcome.safe_to_apply,
        should_learn=outcome.should_learn,
        confidence=breakdown,
        evidence=evidence,
    )
