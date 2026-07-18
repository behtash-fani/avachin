#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ingest DetectionResult reports and calculate official benchmark metrics."""

from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.benchmark_contract import (
    AUTO_APPLY_DECISIONS,
    BenchmarkManifest,
    GeneratedSample,
    normalize_identity_key,
    text_identity_key,
)


def path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _score(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def predicted_identity_keys(detection: Mapping[str, Any]) -> tuple[str, ...]:
    evidence = detection.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    external = evidence.get("external_identifiers")
    if not isinstance(external, Mapping):
        external = {}
    stable_keys: list[str] = []
    prefixes = {
        "avachin_recording": "avachin",
        "isrc": "isrc",
        "musicbrainz_recording": "musicbrainz",
        "spotify_track": "spotify",
        "apple_track": "apple",
    }
    for field, prefix in prefixes.items():
        value = str(external.get(field) or "").strip()
        if value:
            stable_keys.append(normalize_identity_key(f"{prefix}:{value}"))
    stable_keys = list(dict.fromkeys(key for key in stable_keys if key))
    if stable_keys:
        return tuple(stable_keys)
    text_key = text_identity_key(detection.get("artist"), detection.get("title"))
    return (text_key,) if text_key else ()


@dataclass(frozen=True)
class EvaluationRow:
    sample_id: str
    expected_recording_id: str
    predicted_recording_id: str
    transform_id: str
    transform_kind: str
    split: str
    version: str
    hard_negative_group: str
    decision: str
    provider: str
    match_mode: str
    correct: bool
    identified: bool
    auto_apply: bool
    false_auto_apply: bool
    audio_confidence: float | None
    metadata_confidence: float | None
    identity_confidence: float | None
    overall_confidence: float | None
    candidate_margin: float | None
    query_seconds: float | None
    expected_identity_keys: tuple[str, ...]
    predicted_identity_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_identity_keys"] = list(self.expected_identity_keys)
        payload["predicted_identity_keys"] = list(self.predicted_identity_keys)
        return payload


def evaluate_detections(
    *,
    manifest: BenchmarkManifest,
    samples: Sequence[GeneratedSample],
    detection_report: Mapping[str, Any],
    corpus_root: Path,
) -> list[EvaluationRow]:
    detections = detection_report.get("detections")
    if not isinstance(detections, list):
        raise ValueError("detection report requires a detections list")
    detection_by_path: dict[str, Mapping[str, Any]] = {}
    for raw in detections:
        if not isinstance(raw, Mapping):
            continue
        source = str(raw.get("source_path") or "").strip()
        if source:
            detection_by_path[path_key(source)] = raw

    owners = manifest.identity_owner_map()
    rows: list[EvaluationRow] = []
    for sample in samples:
        sample_path = (Path(corpus_root).resolve() / sample.path).resolve()
        detection = detection_by_path.get(path_key(sample_path), {})
        predicted_keys = predicted_identity_keys(detection)
        expected_keys = tuple(sample.expected_identity_keys)
        correct = bool(set(expected_keys).intersection(predicted_keys))
        predicted_recording_id = ""
        for key in predicted_keys:
            owner = owners.get(key)
            if owner:
                predicted_recording_id = owner
                break
        decision = str(detection.get("decision") or "REJECT").strip().upper()
        identified = bool(predicted_keys) and decision != "REJECT"
        auto_apply = decision in AUTO_APPLY_DECISIONS
        evidence = detection.get("evidence") if isinstance(detection.get("evidence"), Mapping) else {}
        confidence = detection.get("confidence") if isinstance(detection.get("confidence"), Mapping) else {}
        rows.append(
            EvaluationRow(
                sample_id=sample.sample_id,
                expected_recording_id=sample.expected_recording_id,
                predicted_recording_id=predicted_recording_id,
                transform_id=sample.transform_id,
                transform_kind=sample.transform_kind,
                split=sample.split,
                version=sample.version,
                hard_negative_group=sample.hard_negative_group,
                decision=decision,
                provider=str(evidence.get("provider") or ""),
                match_mode=str(evidence.get("match_mode") or ""),
                correct=correct,
                identified=identified,
                auto_apply=auto_apply,
                false_auto_apply=bool(auto_apply and not correct),
                audio_confidence=_score(confidence.get("audio")),
                metadata_confidence=_score(confidence.get("metadata")),
                identity_confidence=_score(confidence.get("identity")),
                overall_confidence=_score(confidence.get("overall")),
                candidate_margin=_score(evidence.get("candidate_margin")),
                query_seconds=(
                    float(detection.get("query_seconds"))
                    if detection.get("query_seconds") not in (None, "")
                    else None
                ),
                expected_identity_keys=expected_keys,
                predicted_identity_keys=predicted_keys,
            )
        )
    return rows


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 6)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 6)


def summarize_rows(rows: Sequence[EvaluationRow]) -> dict[str, Any]:
    total = len(rows)
    true_positive = sum(row.correct and row.identified for row in rows)
    false_positive = sum(row.identified and not row.correct for row in rows)
    auto_apply_total = sum(row.auto_apply for row in rows)
    correct_auto_apply = sum(row.auto_apply and row.correct for row in rows)
    false_auto_apply = sum(row.false_auto_apply for row in rows)
    review = sum(row.decision == "REVIEW" for row in rows)
    reject = sum(row.decision == "REJECT" for row in rows)
    unknown = sum(not row.identified for row in rows)
    query_times = [row.query_seconds for row in rows if row.query_seconds is not None]
    hard_negative_confusions = sum(
        bool(
            row.hard_negative_group
            and row.predicted_recording_id
            and row.predicted_recording_id != row.expected_recording_id
        )
        for row in rows
    )
    return {
        "total": total,
        "identified": sum(row.identified for row in rows),
        "correct": sum(row.correct for row in rows),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "precision": _ratio(true_positive, true_positive + false_positive),
        "recall": _ratio(true_positive, total),
        "unknown_rate": _ratio(unknown, total),
        "review_rate": _ratio(review, total),
        "reject_rate": _ratio(reject, total),
        "auto_apply_total": auto_apply_total,
        "correct_auto_apply": correct_auto_apply,
        "false_auto_apply": false_auto_apply,
        "false_auto_apply_rate": _ratio(false_auto_apply, auto_apply_total),
        "auto_apply_precision": _ratio(correct_auto_apply, auto_apply_total),
        "auto_apply_recall": _ratio(correct_auto_apply, total),
        "hard_negative_confusions": hard_negative_confusions,
        "query_seconds_mean": round(statistics.fmean(query_times), 6) if query_times else None,
        "query_seconds_p50": _percentile(query_times, 0.50),
        "query_seconds_p95": _percentile(query_times, 0.95),
        "gate_false_auto_apply_zero": false_auto_apply == 0,
    }


def benchmark_report(
    rows: Sequence[EvaluationRow],
    *,
    benchmark_name: str,
    avachin_version: str,
    git_commit: str,
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    by_transform: dict[str, Any] = {}
    for transform in sorted({row.transform_id for row in rows}):
        by_transform[transform] = summarize_rows(
            [row for row in rows if row.transform_id == transform]
        )
    by_split: dict[str, Any] = {}
    for split in sorted({row.split for row in rows}):
        by_split[split] = summarize_rows([row for row in rows if row.split == split])
    return {
        "schema_version": 1,
        "benchmark_name": benchmark_name,
        "avachin_version": avachin_version,
        "git_commit": git_commit,
        "configuration": dict(configuration),
        "summary": summarize_rows(rows),
        "by_transform": by_transform,
        "by_split": by_split,
        "rows": [row.to_dict() for row in rows],
    }


def load_generated_samples(path: Path) -> tuple[dict[str, Any], list[GeneratedSample]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or int(payload.get("schema_version") or 0) != 1:
        raise ValueError("unsupported generated benchmark manifest")
    rows = payload.get("samples")
    if not isinstance(rows, list):
        raise ValueError("generated manifest requires samples")
    samples = [
        GeneratedSample(
            sample_id=str(item["sample_id"]),
            expected_recording_id=str(item["expected_recording_id"]),
            source_reference_path=str(item["source_reference_path"]),
            path=str(item["path"]),
            transform_id=str(item["transform_id"]),
            transform_kind=str(item["transform_kind"]),
            split=str(item["split"]),
            version=str(item.get("version") or ""),
            hard_negative_group=str(item.get("hard_negative_group") or ""),
            expected_identity_keys=tuple(item.get("expected_identity_keys") or []),
            parameters=dict(item.get("parameters") or {}),
        )
        for item in rows
        if isinstance(item, Mapping)
    ]
    return dict(payload), samples
