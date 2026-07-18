#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrate conservative DetectionResult thresholds from validation rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from tools.benchmark_metrics import EvaluationRow

DEFAULT_IDENTITY_VALUES = (86.0, 88.0, 90.0, 92.0, 94.0, 96.0, 98.0)
DEFAULT_AUDIO_VALUES = (86.0, 88.0, 90.0, 92.0, 94.0, 96.0, 98.0)
DEFAULT_METADATA_VALUES = (80.0, 85.0, 90.0, 95.0)
DEFAULT_MARGIN_VALUES = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
DEFAULT_REVIEW_VALUES = (60.0, 70.0, 80.0)


@dataclass(frozen=True)
class ThresholdProfile:
    identity_min: float
    audio_min: float
    metadata_min: float
    partial_margin_min: float
    review_min: float

    def to_config(self) -> dict[str, float]:
        return {
            "detection_local_min_confidence": self.identity_min,
            "detection_local_audio_min_confidence": self.audio_min,
            "detection_local_metadata_min_confidence": self.metadata_min,
            "detection_partial_min_margin": self.partial_margin_min,
            "detection_review_min_confidence": self.review_min,
        }


@dataclass(frozen=True)
class CalibrationScore:
    profile: ThresholdProfile
    total: int
    auto_apply_total: int
    correct_auto_apply: int
    false_auto_apply: int
    review_total: int
    reject_total: int

    @property
    def auto_apply_recall(self) -> float:
        return self.correct_auto_apply / self.total if self.total else 0.0

    @property
    def auto_apply_precision(self) -> float:
        return (
            self.correct_auto_apply / self.auto_apply_total
            if self.auto_apply_total
            else 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_config(),
            "total": self.total,
            "auto_apply_total": self.auto_apply_total,
            "correct_auto_apply": self.correct_auto_apply,
            "false_auto_apply": self.false_auto_apply,
            "auto_apply_precision": round(self.auto_apply_precision, 6),
            "auto_apply_recall": round(self.auto_apply_recall, 6),
            "review_total": self.review_total,
            "reject_total": self.reject_total,
            "gate_false_auto_apply_zero": self.false_auto_apply == 0,
        }


def _value(value: float | None, default: float = 0.0) -> float:
    return default if value is None else float(value)


def classify(row: EvaluationRow, profile: ThresholdProfile) -> str:
    if not row.identified:
        return "REJECT"
    identity = _value(row.identity_confidence)
    metadata = _value(row.metadata_confidence)
    audio = row.audio_confidence
    margin = row.candidate_margin
    audio_ok = audio is None or audio >= profile.audio_min
    metadata_ok = metadata >= profile.metadata_min
    partial_ok = (
        row.match_mode != "segment"
        or (margin is not None and margin >= profile.partial_margin_min)
    )
    if (
        identity >= profile.identity_min
        and metadata_ok
        and audio_ok
        and partial_ok
    ):
        return "AUTO_APPLY"
    overall = _value(row.overall_confidence)
    return "REVIEW" if overall >= profile.review_min else "REJECT"


def score_profile(
    rows: Sequence[EvaluationRow],
    profile: ThresholdProfile,
) -> CalibrationScore:
    auto_apply_total = 0
    correct_auto_apply = 0
    false_auto_apply = 0
    review_total = 0
    reject_total = 0
    for row in rows:
        decision = classify(row, profile)
        if decision == "AUTO_APPLY":
            auto_apply_total += 1
            if row.correct:
                correct_auto_apply += 1
            else:
                false_auto_apply += 1
        elif decision == "REVIEW":
            review_total += 1
        else:
            reject_total += 1
    return CalibrationScore(
        profile=profile,
        total=len(rows),
        auto_apply_total=auto_apply_total,
        correct_auto_apply=correct_auto_apply,
        false_auto_apply=false_auto_apply,
        review_total=review_total,
        reject_total=reject_total,
    )


def search_space_size(
    *,
    identity_values: Sequence[float],
    audio_values: Sequence[float],
    metadata_values: Sequence[float],
    margin_values: Sequence[float],
    review_values: Sequence[float],
) -> int:
    return sum(
        1
        for identity in identity_values
        for _audio in audio_values
        for _metadata in metadata_values
        for _margin in margin_values
        for review in review_values
        if review <= identity
    )


def calibrate(
    rows: Sequence[EvaluationRow],
    *,
    identity_values: Iterable[float] | None = None,
    audio_values: Iterable[float] | None = None,
    metadata_values: Iterable[float] | None = None,
    margin_values: Iterable[float] | None = None,
    review_values: Iterable[float] | None = None,
) -> tuple[CalibrationScore, list[CalibrationScore]]:
    validation = [row for row in rows if row.split == "validation"] or list(rows)
    if not validation:
        raise ValueError("threshold calibration requires evaluation rows")
    identities = tuple(identity_values or DEFAULT_IDENTITY_VALUES)
    audios = tuple(audio_values or DEFAULT_AUDIO_VALUES)
    metadata_scores = tuple(metadata_values or DEFAULT_METADATA_VALUES)
    margins = tuple(margin_values or DEFAULT_MARGIN_VALUES)
    reviews = tuple(review_values or DEFAULT_REVIEW_VALUES)
    if not all((identities, audios, metadata_scores, margins, reviews)):
        raise ValueError("threshold calibration grids must not be empty")

    safe: list[CalibrationScore] = []
    for identity in identities:
        for audio in audios:
            for metadata in metadata_scores:
                for margin in margins:
                    for review in reviews:
                        if review > identity:
                            continue
                        score = score_profile(
                            validation,
                            ThresholdProfile(
                                identity_min=float(identity),
                                audio_min=float(audio),
                                metadata_min=float(metadata),
                                partial_margin_min=float(margin),
                                review_min=float(review),
                            ),
                        )
                        if score.false_auto_apply == 0:
                            safe.append(score)
    if not safe:
        raise RuntimeError("no threshold profile achieved zero False Auto-Apply")
    safe.sort(
        key=lambda item: (
            item.correct_auto_apply,
            -item.review_total,
            -item.profile.identity_min,
            -item.profile.audio_min,
            -item.profile.metadata_min,
            -item.profile.partial_margin_min,
            item.profile.review_min,
        ),
        reverse=True,
    )
    return safe[0], safe


def calibration_report(
    best: CalibrationScore,
    safe_profiles: Sequence[CalibrationScore],
    *,
    avachin_version: str,
    git_commit: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "avachin_version": avachin_version,
        "git_commit": git_commit,
        "selection_rule": (
            "False Auto-Apply must equal zero; then maximize correct "
            "auto-applies and minimize review volume."
        ),
        "default_search_space": search_space_size(
            identity_values=DEFAULT_IDENTITY_VALUES,
            audio_values=DEFAULT_AUDIO_VALUES,
            metadata_values=DEFAULT_METADATA_VALUES,
            margin_values=DEFAULT_MARGIN_VALUES,
            review_values=DEFAULT_REVIEW_VALUES,
        ),
        "best": best.to_dict(),
        "safe_profile_count": len(safe_profiles),
        "top_safe_profiles": [item.to_dict() for item in safe_profiles[:25]],
    }
