#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the versioned DetectionResult contract on the canonical runtime."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from tools import avachin_partial_fingerprint_launcher as previous
from tools.detection_contract import (
    ConfidenceBreakdown,
    DetectionDecision,
    DetectionEvidence,
    DetectionResult,
)
from tools.detection_report import (
    canonical_source_key,
    write_detection_reports,
)
from tools.identity_resolver import resolve_candidate

app = previous.app
LAUNCHER_VERSION = "12.7"

_ORIGINAL_DETERMINE_CANDIDATE = getattr(
    app.determine_candidate,
    "__avachin_original_detection_contract__",
    app.determine_candidate,
)
_ORIGINAL_WRITE_CSV = getattr(
    app.write_csv,
    "__avachin_original_detection_report__",
    app.write_csv,
)
_DETECTIONS: dict[str, DetectionResult] = {}
_QUERY_TIMINGS: dict[str, float] = {}
_DETECTIONS_LOCK = threading.RLock()


def _fallback_detection(
    source: Path,
    candidate: Any,
) -> DetectionResult:
    title = " ".join(
        str(getattr(candidate, "title", "") or "").split()
    )
    artist = " ".join(
        str(getattr(candidate, "artist", "") or "").split()
    )
    album = " ".join(
        str(getattr(candidate, "album", "") or "").split()
    )
    valid = bool(
        title
        and artist
        and title.casefold() not in {"untitled", "unknown title"}
        and artist.casefold() not in {"unknown", "unknown artist"}
    )
    decision = (
        DetectionDecision.REVIEW
        if valid
        else DetectionDecision.REJECT
    )
    confidence = max(
        0.0,
        min(
            100.0,
            float(getattr(candidate, "confidence", 0.0) or 0.0),
        ),
    )
    return DetectionResult(
        source_path=str(source),
        title=title,
        artist=artist,
        album=album,
        decision=decision,
        decision_reason="detection-contract-failed-safe",
        safe_to_apply=False,
        should_learn=False,
        confidence=ConfidenceBreakdown(
            audio=None,
            metadata=0.0,
            identity=round(confidence, 2),
            overall=round(confidence * 0.55, 2),
        ),
        evidence=DetectionEvidence(
            provider=str(
                getattr(candidate, "source", "") or ""
            ).casefold(),
            match_mode="contract-error",
            flags=("contract_error",),
        ),
    )


def attach_detection_contract(
    *,
    source: Path,
    audio: Any,
    candidate: Any,
    config: dict[str, Any],
    min_confidence: float,
) -> DetectionResult:
    detection = resolve_candidate(
        source_path=source,
        audio=audio,
        candidate=candidate,
        config=config,
        min_confidence=min_confidence,
    )
    evidence = getattr(candidate, "evidence", None)
    if not isinstance(evidence, dict):
        evidence = {}
        candidate.evidence = evidence
    evidence["detection_result"] = detection.to_dict()
    evidence["detection_decision"] = detection.decision.value
    evidence["detection_reason"] = detection.decision_reason
    evidence["detection_safe_to_apply"] = detection.safe_to_apply
    with _DETECTIONS_LOCK:
        _DETECTIONS[canonical_source_key(source)] = detection
    return detection


def _determine_candidate_with_detection_contract(
    source: Path,
    audio: Any,
    default_artist: str,
    normalize_persian: bool,
    config: dict[str, Any],
    client: Any,
    min_confidence: float,
    verify_online: bool,
    offline: bool,
    unknown_artist_folder: str,
    fpcalc_path: Path | None = None,
) -> tuple[Any, list[str]]:
    started = time.perf_counter()
    candidate, errors = _ORIGINAL_DETERMINE_CANDIDATE(
        source,
        audio,
        default_artist,
        normalize_persian,
        config,
        client,
        min_confidence,
        verify_online,
        offline,
        unknown_artist_folder,
        fpcalc_path,
    )
    query_seconds = round(time.perf_counter() - started, 6)
    key = canonical_source_key(source)
    errors = list(errors or [])
    evidence = getattr(candidate, "evidence", None)
    if not isinstance(evidence, dict):
        evidence = {}
        candidate.evidence = evidence
    evidence["detection_query_seconds"] = query_seconds
    with _DETECTIONS_LOCK:
        _QUERY_TIMINGS[key] = query_seconds
    try:
        attach_detection_contract(
            source=source,
            audio=audio,
            candidate=candidate,
            config=config,
            min_confidence=min_confidence,
        )
    except Exception as exc:
        detection = _fallback_detection(source, candidate)
        evidence["detection_result"] = detection.to_dict()
        evidence["detection_decision"] = detection.decision.value
        evidence["detection_reason"] = detection.decision_reason
        evidence["detection_safe_to_apply"] = False
        evidence["detection_contract_error"] = str(exc)[:500]
        with _DETECTIONS_LOCK:
            _DETECTIONS[key] = detection
        errors.append(f"Detection contract warning: {exc}")
    return candidate, errors


def _write_csv_with_detection_reports(
    path: Path,
    results: list[Any],
) -> None:
    _ORIGINAL_WRITE_CSV(path, results)
    with _DETECTIONS_LOCK:
        snapshot = dict(_DETECTIONS)
        timing_snapshot = dict(_QUERY_TIMINGS)
    json_path, csv_path, _ = write_detection_reports(
        Path(path).parent,
        results,
        snapshot,
        avachin_version=str(app.APP_VERSION),
        query_timings=timing_snapshot,
    )
    print(f"JSON summary: {json_path}")
    print(f"CSV report: {csv_path}")
    with _DETECTIONS_LOCK:
        for key in snapshot:
            _DETECTIONS.pop(key, None)
            _QUERY_TIMINGS.pop(key, None)


setattr(
    _determine_candidate_with_detection_contract,
    "__avachin_original_detection_contract__",
    _ORIGINAL_DETERMINE_CANDIDATE,
)
setattr(
    _determine_candidate_with_detection_contract,
    "__avachin_detection_contract__",
    True,
)
setattr(
    _write_csv_with_detection_reports,
    "__avachin_original_detection_report__",
    _ORIGINAL_WRITE_CSV,
)
setattr(
    _write_csv_with_detection_reports,
    "__avachin_detection_report__",
    True,
)


def install_detection_runtime() -> None:
    if not getattr(
        app.determine_candidate,
        "__avachin_detection_contract__",
        False,
    ):
        app.determine_candidate = (
            _determine_candidate_with_detection_contract
        )
    if not getattr(
        app.write_csv,
        "__avachin_detection_report__",
        False,
    ):
        app.write_csv = _write_csv_with_detection_reports
    app.APP_VERSION = LAUNCHER_VERSION
    app.DetectionDecision = DetectionDecision
    app.DetectionResultContract = DetectionResult
    app.resolve_detection_candidate = resolve_candidate


install_detection_runtime()


if __name__ == "__main__":
    raise SystemExit(app.main())
