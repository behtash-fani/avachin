#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review, quarantine and re-score an Avachin benchmark without rerunning audio.

The real audio corpus and review ledger stay local. A confirmed contaminated
reference is excluded from release gates, but remains visible in a reviewed
report with the user's reason and corrected identity. Re-analysis consumes the
existing DetectionResult artifacts, so it does not regenerate audio or run the
organizer again.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_contract import BenchmarkManifest  # noqa: E402
from tools.benchmark_metrics import (  # noqa: E402
    EvaluationRow,
    benchmark_report,
    evaluate_detections,
    load_generated_samples,
)
from tools.benchmark_thresholds import calibrate, calibration_report  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402

REVIEW_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        delete=False,
        dir=path.parent,
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)
    return path


def _atomic_csv(path: Path, rows: Sequence[EvaluationRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [item.name for item in fields(EvaluationRow)]
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=path.parent,
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=names)
        writer.writeheader()
        for row in rows:
            payload = row.to_dict()
            payload["expected_identity_keys"] = json.dumps(
                payload["expected_identity_keys"], ensure_ascii=False
            )
            payload["predicted_identity_keys"] = json.dumps(
                payload["predicted_identity_keys"], ensure_ascii=False
            )
            writer.writerow(payload)
        temporary = Path(stream.name)
    temporary.replace(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return dict(payload)


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def default_review_path(corpus_root: Path) -> Path:
    return Path(corpus_root).expanduser().resolve() / "review.json"


def empty_review() -> dict[str, Any]:
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "updated_at": utc_now(),
        "references": {},
    }


def load_review(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return empty_review()
    payload = _read_json(path)
    if int(payload.get("schema_version") or 0) != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported benchmark review schema")
    references = payload.get("references")
    if not isinstance(references, dict):
        raise ValueError("benchmark review requires a references object")
    payload["references"] = dict(references)
    return payload


def quarantine_reference(
    *,
    manifest_path: Path,
    review_path: Path,
    recording_id: str,
    reason: str,
    confirmed_artist: str = "",
    confirmed_title: str = "",
    confirmed_by: str = "user",
) -> dict[str, Any]:
    manifest = BenchmarkManifest.load(Path(manifest_path))
    references = manifest.reference_map()
    recording_id = str(recording_id or "").strip()
    if recording_id not in references:
        raise ValueError(f"recording is not present in the manifest: {recording_id}")
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise ValueError("quarantine reason is required")

    review = load_review(Path(review_path))
    entry = {
        "status": "quarantined",
        "reason": reason,
        "confirmed_artist": " ".join(str(confirmed_artist or "").split()),
        "confirmed_title": " ".join(str(confirmed_title or "").split()),
        "confirmed_by": " ".join(str(confirmed_by or "user").split()) or "user",
        "confirmed_at": utc_now(),
        "manifest_artist": references[recording_id].artist,
        "manifest_title": references[recording_id].title,
        "reference_path": references[recording_id].path,
    }
    review["updated_at"] = utc_now()
    review["references"][recording_id] = entry
    _atomic_json(Path(review_path), review)
    return {"recording_id": recording_id, **entry, "review_path": str(review_path)}


def restore_reference(*, review_path: Path, recording_id: str) -> dict[str, Any]:
    review = load_review(Path(review_path))
    recording_id = str(recording_id or "").strip()
    removed = review["references"].pop(recording_id, None)
    review["updated_at"] = utc_now()
    _atomic_json(Path(review_path), review)
    return {
        "recording_id": recording_id,
        "restored": removed is not None,
        "review_path": str(review_path),
    }


def quarantined_entries(review: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    references = review.get("references")
    if not isinstance(references, Mapping):
        return {}
    return {
        str(recording_id): dict(entry)
        for recording_id, entry in references.items()
        if isinstance(entry, Mapping)
        and str(entry.get("status") or "").casefold() == "quarantined"
    }


def newest_run(report_root: Path) -> Path:
    report_root = Path(report_root).expanduser().resolve()
    candidates = sorted(
        (
            path
            for path in report_root.glob("run-*")
            if path.is_dir() and (path / "detection-report.json").is_file()
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no completed benchmark run was found under {report_root}")
    return candidates[0]


def reanalyze_run(
    *,
    run_dir: Path,
    corpus_root: Path | None = None,
    review_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).expanduser().resolve()
    pipeline_path = run_dir / "pipeline-report.json"
    pipeline = _read_json(pipeline_path) if pipeline_path.is_file() else {}
    resolved_corpus = Path(
        corpus_root or pipeline.get("corpus_root") or PROJECT_ROOT / "benchmark"
    ).expanduser().resolve()
    resolved_review = Path(review_path or default_review_path(resolved_corpus)).expanduser().resolve()

    manifest_path = run_dir / "manifest.snapshot.json"
    generated_path = run_dir / "generated-manifest.json"
    detection_path = run_dir / "detection-report.json"
    for required in (manifest_path, generated_path, detection_path):
        if not required.is_file():
            raise FileNotFoundError(required)

    manifest = BenchmarkManifest.load(manifest_path)
    _, samples = load_generated_samples(generated_path)
    detection = _read_json(detection_path)
    review = load_review(resolved_review)
    excluded = quarantined_entries(review)
    unknown_exclusions = sorted(set(excluded).difference(manifest.reference_map()))
    if unknown_exclusions:
        raise ValueError(
            "review contains recording IDs missing from this manifest: "
            + ", ".join(unknown_exclusions)
        )

    included_samples = [
        sample for sample in samples if sample.expected_recording_id not in excluded
    ]
    excluded_samples = [
        sample for sample in samples if sample.expected_recording_id in excluded
    ]
    if not included_samples:
        raise ValueError("all benchmark samples are quarantined")

    rows = evaluate_detections(
        manifest=manifest,
        samples=included_samples,
        detection_report=detection,
        corpus_root=resolved_corpus,
    )
    original_report_path = run_dir / "benchmark-report.json"
    original_report = _read_json(original_report_path) if original_report_path.is_file() else {}
    configuration = original_report.get("configuration")
    if not isinstance(configuration, Mapping):
        configuration = {}
    configuration = {
        **dict(configuration),
        "review_file": str(resolved_review),
        "quarantined_recordings": sorted(excluded),
        "quarantined_samples": len(excluded_samples),
    }
    report = benchmark_report(
        rows,
        benchmark_name=manifest.name,
        avachin_version=AVACHIN_VERSION,
        git_commit=_git_commit(),
        configuration=configuration,
    )
    report["review"] = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "path": str(resolved_review),
        "quarantined_recordings": excluded,
        "quarantined_recording_count": len(excluded),
        "quarantined_sample_count": len(excluded_samples),
        "included_sample_count": len(included_samples),
    }

    benchmark_json = run_dir / "benchmark-reviewed-report.json"
    benchmark_csv = run_dir / "benchmark-reviewed-report.csv"
    threshold_json = run_dir / "threshold-reviewed-profile.json"
    reviewed_pipeline_json = run_dir / "pipeline-reviewed-report.json"
    _atomic_json(benchmark_json, report)
    _atomic_csv(benchmark_csv, rows)

    try:
        best, safe_profiles = calibrate(rows)
        calibration = calibration_report(
            best,
            safe_profiles,
            avachin_version=AVACHIN_VERSION,
            git_commit=_git_commit(),
        )
        calibration["status"] = "safe-profile"
    except RuntimeError as exc:
        calibration = {
            "schema_version": 1,
            "status": "no-safe-profile",
            "avachin_version": AVACHIN_VERSION,
            "git_commit": _git_commit(),
            "error": str(exc),
            "selection_rule": "No profile with zero False Auto-Apply was found.",
        }
    _atomic_json(threshold_json, calibration)

    passed = bool(report["summary"].get("gate_false_auto_apply_zero"))
    result = {
        "schema_version": 1,
        "status": "passed" if passed else "gate-failed",
        "generated_at": utc_now(),
        "avachin_version": AVACHIN_VERSION,
        "git_commit": _git_commit(),
        "run_dir": str(run_dir),
        "corpus_root": str(resolved_corpus),
        "source_pipeline_report": str(pipeline_path) if pipeline_path.is_file() else "",
        "review_file": str(resolved_review),
        "review": report["review"],
        "benchmark_summary": report["summary"],
        "calibration": calibration,
        "artifacts": {
            "benchmark_json": str(benchmark_json),
            "benchmark_csv": str(benchmark_csv),
            "threshold_profile": str(threshold_json),
            "reviewed_pipeline_report": str(reviewed_pipeline_json),
        },
    }
    _atomic_json(reviewed_pipeline_json, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Quarantine confirmed contaminated benchmark references and re-score "
            "an existing run without regenerating audio or running Preview again."
        )
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=PROJECT_ROOT / "benchmark",
        help="Local benchmark corpus root.",
    )
    parser.add_argument(
        "--review",
        type=Path,
        help="Review ledger path. Defaults to <corpus-root>/review.json.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    quarantine = subparsers.add_parser("quarantine", help="Exclude one confirmed bad reference")
    quarantine.add_argument("--manifest", type=Path)
    quarantine.add_argument("--recording-id", required=True)
    quarantine.add_argument("--reason", required=True)
    quarantine.add_argument("--confirmed-artist", default="")
    quarantine.add_argument("--confirmed-title", default="")
    quarantine.add_argument("--confirmed-by", default="user")

    restore = subparsers.add_parser("restore", help="Remove a reference from quarantine")
    restore.add_argument("--recording-id", required=True)

    subparsers.add_parser("list", help="Print the local review ledger")

    reanalyze = subparsers.add_parser(
        "reanalyze",
        help="Re-score saved artifacts without FFmpeg or organizer execution",
    )
    reanalyze.add_argument("--run-dir", type=Path)
    reanalyze.add_argument(
        "--report-root",
        type=Path,
        default=PROJECT_ROOT / "reports" / "benchmark",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    corpus_root = Path(args.corpus_root).expanduser().resolve()
    review_path = Path(args.review or default_review_path(corpus_root)).expanduser().resolve()
    try:
        if args.command == "quarantine":
            manifest_path = Path(args.manifest or corpus_root / "manifest.json").expanduser().resolve()
            result = quarantine_reference(
                manifest_path=manifest_path,
                review_path=review_path,
                recording_id=args.recording_id,
                reason=args.reason,
                confirmed_artist=args.confirmed_artist,
                confirmed_title=args.confirmed_title,
                confirmed_by=args.confirmed_by,
            )
        elif args.command == "restore":
            result = restore_reference(
                review_path=review_path,
                recording_id=args.recording_id,
            )
        elif args.command == "list":
            result = load_review(review_path)
        else:
            run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else newest_run(args.report_root)
            result = reanalyze_run(
                run_dir=run_dir,
                corpus_root=corpus_root,
                review_path=review_path,
            )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "reanalyze" and result.get("status") == "gate-failed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
