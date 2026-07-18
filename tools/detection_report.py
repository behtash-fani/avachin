#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine-readable JSON/CSV reports for DetectionResult contracts."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.detection_contract import (
    DETECTION_SCHEMA_VERSION,
    DetectionDecision,
    DetectionResult,
)


def canonical_source_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=path.parent,
    ) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    temporary.replace(path)


def _rejected_runtime_result(
    result: Any,
    query_seconds: float | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": DETECTION_SCHEMA_VERSION,
        "source_path": str(
            getattr(result, "source_path", "") or ""
        ),
        "title": "",
        "artist": "",
        "album": "",
        "decision": DetectionDecision.REJECT.value,
        "decision_reason": "runtime-read-or-identification-error",
        "safe_to_apply": False,
        "should_learn": False,
        "confidence": {
            "audio": None,
            "metadata": 0.0,
            "identity": 0.0,
            "overall": 0.0,
        },
        "evidence": {
            "provider": "",
            "match_mode": "runtime-error",
            "flags": ["runtime_error"],
        },
        "runtime_status": str(
            getattr(result, "status", "") or ""
        ),
        "runtime_error": str(
            getattr(result, "error", "") or ""
        ),
    }
    if query_seconds is not None:
        payload["query_seconds"] = round(float(query_seconds), 6)
    return payload


def detection_rows(
    runtime_results: Iterable[Any],
    detections: Mapping[str, DetectionResult],
    query_timings: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    timings = query_timings or {}

    for runtime in runtime_results:
        if str(
            getattr(runtime, "item_type", "") or ""
        ) != "mp3":
            continue
        source_path = str(
            getattr(runtime, "source_path", "") or ""
        )
        key = canonical_source_key(source_path)
        detection = detections.get(key)
        timing = timings.get(key)
        if detection is None:
            rows.append(_rejected_runtime_result(runtime, timing))
            continue

        payload = detection.to_dict()
        if timing is not None:
            payload["query_seconds"] = round(float(timing), 6)
        payload["runtime_status"] = str(
            getattr(runtime, "status", "") or ""
        )
        runtime_error = str(
            getattr(runtime, "error", "") or ""
        )
        if runtime_error:
            payload["runtime_error"] = runtime_error
        rows.append(payload)
        seen.add(key)

    for key, detection in detections.items():
        if key not in seen:
            payload = detection.to_dict()
            timing = timings.get(key)
            if timing is not None:
                payload["query_seconds"] = round(float(timing), 6)
            rows.append(payload)
    return rows


def _flat_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    confidence = (
        payload.get("confidence")
        if isinstance(payload.get("confidence"), Mapping)
        else {}
    )
    evidence = (
        payload.get("evidence")
        if isinstance(payload.get("evidence"), Mapping)
        else {}
    )
    agreement = (
        evidence.get("metadata_agreement")
        if isinstance(evidence.get("metadata_agreement"), Mapping)
        else {}
    )
    return {
        "source_path": payload.get("source_path", ""),
        "decision": payload.get("decision", ""),
        "safe_to_apply": payload.get("safe_to_apply", False),
        "should_learn": payload.get("should_learn", False),
        "provider": evidence.get("provider", ""),
        "match_mode": evidence.get("match_mode", ""),
        "title": payload.get("title", ""),
        "artist": payload.get("artist", ""),
        "album": payload.get("album", ""),
        "audio_confidence": confidence.get("audio"),
        "metadata_confidence": confidence.get("metadata"),
        "identity_confidence": confidence.get("identity"),
        "overall_confidence": confidence.get("overall"),
        "title_agreement": agreement.get("title"),
        "artist_agreement": agreement.get("artist"),
        "duration_agreement": agreement.get("duration"),
        "fingerprint_score": evidence.get("fingerprint_score"),
        "segment_coverage": evidence.get("segment_coverage"),
        "offset_seconds": evidence.get("offset_seconds"),
        "candidate_margin": evidence.get("candidate_margin"),
        "query_seconds": payload.get("query_seconds"),
        "consensus_sources": ",".join(
            str(value)
            for value in (
                evidence.get("consensus_sources", []) or []
            )
        ),
        "external_identifiers": json.dumps(
            evidence.get("external_identifiers", {}),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "flags": ",".join(
            str(value)
            for value in (evidence.get("flags", []) or [])
        ),
        "decision_reason": payload.get("decision_reason", ""),
        "runtime_status": payload.get("runtime_status", ""),
        "runtime_error": payload.get("runtime_error", ""),
    }


def write_detection_reports(
    report_dir: Path,
    runtime_results: Iterable[Any],
    detections: Mapping[str, DetectionResult],
    *,
    avachin_version: str,
    query_timings: Mapping[str, float] | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    report_dir = Path(report_dir)
    rows = detection_rows(runtime_results, detections, query_timings)
    counts = {
        decision.value: sum(
            row.get("decision") == decision.value
            for row in rows
        )
        for decision in DetectionDecision
    }
    payload = {
        "schema_version": DETECTION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ),
        "avachin_version": str(avachin_version),
        "summary": {
            "total": len(rows),
            **counts,
        },
        "detections": rows,
    }
    json_path = report_dir / "detection-report.json"
    csv_path = report_dir / "detection-report.csv"
    _atomic_text(
        json_path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )

    flat = [_flat_row(row) for row in rows]
    fields = list(_flat_row({}).keys())
    report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=report_dir,
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flat)
        temporary = Path(stream.name)
    temporary.replace(csv_path)
    return json_path, csv_path, payload
