#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibrate conservative DetectionResult thresholds from validation rows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from tools.benchmark_metrics import EvaluationRow


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
    decisions = [(row, classify(row, profile)) for row in rows]
    auto_rows = [item for item in decisions if item[1] == "AUTO_APPLY"]
    return CalibrationScore(
        profile=profile,
        total=len(rows),
        auto_apply_total=len(auto_rows),
        correct_auto_apply=sum(row.correct for row, _ in auto_rows),
        false_auto_apply=sum(not row.correct for row, _ in auto_rows),
        review_total=sum(decision == "REVIEW" for _, decision in decisions),
        reject_total=sum(decision == "REJECT" for _, decision in decisions),
    )


def _range(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


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
    identity_values = list(identity_values or _range(80, 100, 2))
    audio_values = list(audio_values or _range(80, 100, 2))
    metadata_values = list(metadata_values or _range(80, 100, 4))
    margin_values = list(margin_values or _range(0, 10, 1))
    review_values = list(review_values or _range(50, 90, 5))
    candidates: list[CalibrationScore] = []
    for identity in identity_values:
        for audio in audio_values:
            for metadata in metadata_values:
                for margin in margin_values:
                    for review in review_values:
                        if review > identity:
                            continue
                        candidates.append(
                            score_profile(
                                validation,
                                ThresholdProfile(
                                    identity_min=float(identity),
                                    audio_min=float(audio),
                                    metadata_min=float(metadata),
                                    partial_margin_min=float(margin),
                                    review_min=float(review),
                                ),
                            )
                        )
    safe = [item for item in candidates if item.false_auto_apply == 0]
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
        "best": best.to_dict(),
        "safe_profile_count": len(safe_profiles),
        "top_safe_profiles": [item.to_dict() for item in safe_profiles[:25]],
    }
