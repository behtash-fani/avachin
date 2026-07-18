#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Explainable confidence calculations for Avachin detections."""

from __future__ import annotations

from tools.detection_contract import ConfidenceBreakdown


def clamp_score(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return round(max(0.0, min(100.0, number)), 2)


def acoustic_score(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= number <= 1.0:
        number *= 100.0
    return clamp_score(number)


def metadata_confidence(
    *,
    title: object,
    artist: object,
    duration: object,
    exact_identifier: bool = False,
) -> float:
    title_score = clamp_score(title)
    artist_score = clamp_score(artist)
    duration_score = clamp_score(duration, 55.0)
    score = (
        0.52 * title_score
        + 0.38 * artist_score
        + 0.10 * duration_score
    )
    if exact_identifier:
        score = max(score, 98.0)
    return clamp_score(score)


def identity_confidence(
    *,
    candidate_confidence: object,
    metadata: object,
    source_quality: object,
    exact_identifier: bool = False,
) -> float:
    candidate = clamp_score(candidate_confidence)
    metadata_score = clamp_score(metadata)
    quality = clamp_score(source_quality, 75.0)
    score = 0.70 * candidate + 0.20 * metadata_score + 0.10 * quality
    if exact_identifier:
        score = max(score, 98.0)
    return clamp_score(score)


def confidence_breakdown(
    *,
    audio: float | None,
    metadata: float,
    identity: float,
) -> ConfidenceBreakdown:
    metadata = clamp_score(metadata)
    identity = clamp_score(identity)
    if audio is None:
        overall = 0.45 * metadata + 0.55 * identity
    else:
        audio = clamp_score(audio)
        overall = 0.55 * audio + 0.20 * metadata + 0.25 * identity
    return ConfidenceBreakdown(
        audio=audio,
        metadata=metadata,
        identity=identity,
        overall=clamp_score(overall),
    )
