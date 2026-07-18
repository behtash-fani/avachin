#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command, Preview-only benchmark pipeline for a real Avachin corpus."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.avachin_operation import OperationEvent, OperationRequest, OperationRunner
from tools.benchmark_bootstrap import bootstrap_manifest
from tools.benchmark_contract import (
    BenchmarkManifest,
    GeneratedSample,
    generated_samples,
    write_generated_manifest,
)
from tools.benchmark_metrics import EvaluationRow, benchmark_report, evaluate_detections
from tools.benchmark_thresholds import calibrate, calibration_report
from tools.benchmark_transforms import materialize_all
from tools.version import AVACHIN_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
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


def _write_evaluation_csv(path: Path, rows: Sequence[EvaluationRow]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_names = [field.name for field in fields(EvaluationRow)]
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        delete=False,
        dir=path.parent,
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=field_names)
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


def _resolve_artifact_path(value: str) -> Path:
    path = Path(str(value or "").strip()).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _copy_if_present(source: Path, target: Path) -> str:
    if not source.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def _pipeline_report(
    *,
    status: str,
    run_dir: Path,
    corpus_root: Path,
    manifest_path: Path,
    generated_manifest_path: Path,
    generated_root: Path,
    operation: Mapping[str, Any] | None,
    benchmark_summary: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
    artifacts: Mapping[str, str],
    stages: Sequence[Mapping[str, Any]],
    error: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "status": status,
        "generated_at": utc_now(),
        "avachin_version": AVACHIN_VERSION,
        "git_commit": git_commit(),
        "run_dir": str(run_dir),
        "corpus_root": str(corpus_root),
        "manifest": str(manifest_path),
        "generated_manifest": str(generated_manifest_path),
        "generated_root": str(generated_root),
        "operation": dict(operation or {}),
        "benchmark_summary": dict(benchmark_summary or {}),
        "calibration": dict(calibration or {}),
        "artifacts": dict(artifacts),
        "stages": [dict(stage) for stage in stages],
    }
    if error:
        payload["error"] = str(error)
    return payload


def run_pipeline(
    *,
    corpus_root: Path,
    manifest_path: Path | None = None,
    report_root: Path | None = None,
    run_dir: Path | None = None,
    db_path: Path | None = None,
    refresh_corpus: bool = False,
    limit: int = 100,
    minimum_duration_seconds: float = 20.0,
    validation_percent: int = 80,
    seed: int = 20260718,
    ffmpeg: str | None = None,
    allow_online: bool = False,
    workers: int | None = None,
    min_confidence: float | None = None,
    normalize_persian: bool = False,
    operation_runner: OperationRunner | None = None,
    materializer: Callable[..., list[Any]] = materialize_all,
    progress_listener: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    corpus_root = Path(corpus_root).expanduser().resolve()
    corpus_root.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path or corpus_root / "manifest.json").expanduser().resolve()
    report_root = Path(
        report_root or PROJECT_ROOT / "reports" / "benchmark"
    ).expanduser().resolve()
    run_dir = Path(
        run_dir or report_root / f"run-{timestamp_token()}"
    ).expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    generated_root_name = f"generated/run-{run_dir.name.removeprefix('run-')}"
    generated_root = (corpus_root / generated_root_name).resolve()
    generated_root.relative_to(corpus_root)
    generated_manifest_path = run_dir / "generated-manifest.json"
    event_log_path = run_dir / "operation-events.jsonl"
    stages: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}

    def announce(stage: str, status: str, **extra: Any) -> None:
        row = {"stage": stage, "status": status, "timestamp": utc_now(), **extra}
        stages.append(row)
        if progress_listener is not None:
            progress_listener(f"[{stage}] {status}")

    should_bootstrap = refresh_corpus or not manifest_path.is_file()
    if should_bootstrap:
        if manifest_path.exists() and not refresh_corpus:
            raise FileExistsError(manifest_path)
        announce("bootstrap", "started")
        bootstrap_result = bootstrap_manifest(
            db_path=Path(db_path).expanduser().resolve() if db_path else _default_db_path(),
            corpus_root=corpus_root,
            output_manifest=manifest_path,
            limit=int(limit),
            minimum_duration_seconds=float(minimum_duration_seconds),
            validation_percent=int(validation_percent),
            seed=int(seed),
        )
        announce("bootstrap", "completed", **bootstrap_result)
    else:
        announce("bootstrap", "reused", manifest=str(manifest_path))

    announce("validate", "started")
    manifest = BenchmarkManifest.load(manifest_path)
    identity_map = manifest.identity_owner_map()
    announce(
        "validate",
        "completed",
        references=len(manifest.references),
        transforms=len(manifest.transforms),
        unique_identity_keys=len(identity_map),
        ambiguous_identity_keys=list(manifest.ambiguous_identity_keys()),
    )
    artifacts["manifest_snapshot"] = _copy_if_present(
        manifest_path, run_dir / "manifest.snapshot.json"
    )

    samples: tuple[GeneratedSample, ...] = generated_samples(
        manifest, generated_root=generated_root_name
    )
    write_generated_manifest(generated_manifest_path, manifest, samples)
    artifacts["generated_manifest"] = str(generated_manifest_path)

    needs_ffmpeg = any(item.kind != "identity" for item in manifest.transforms)
    ffmpeg_path = ffmpeg or shutil.which("ffmpeg")
    if needs_ffmpeg and not ffmpeg_path:
        raise FileNotFoundError("ffmpeg was not found; transformed benchmark samples cannot be generated")
    announce("generate", "started", samples=len(samples))
    materialized = materializer(
        samples=samples,
        references=manifest.references,
        transforms=manifest.transforms,
        corpus_root=corpus_root,
        ffmpeg=str(ffmpeg_path or "ffmpeg-not-required"),
        global_seed=manifest.seed,
    )
    announce("generate", "completed", materialized=len(materialized))

    detection_report_path: Path | None = None
    operation_events: list[dict[str, Any]] = []
    runner = operation_runner or OperationRunner()
    request = OperationRequest(
        operation="organizer-preview",
        root=str(generated_root),
        offline=not allow_online,
        workers=workers,
        min_confidence=min_confidence,
        normalize_persian=normalize_persian,
    )
    announce(
        "preview",
        "started",
        offline=not allow_online,
        root=str(generated_root),
    )
    with event_log_path.open("w", encoding="utf-8", newline="") as event_stream:
        def listener(event: OperationEvent) -> None:
            nonlocal detection_report_path
            payload = event.to_dict()
            operation_events.append(payload)
            event_stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
            event_stream.flush()
            if (
                event.event_type == "artifact"
                and event.path
                and Path(event.path).name.casefold() == "detection-report.json"
            ):
                detection_report_path = _resolve_artifact_path(event.path)
            if progress_listener is not None and event.event_type in {
                "phase",
                "progress",
                "warning",
                "error",
                "completed",
                "failed",
            }:
                progress_listener(
                    f"[preview:{event.event_type}] {event.message or event.status}"
                )

        operation_result = runner.run(request, listener=listener)
    artifacts["operation_events"] = str(event_log_path)
    announce("preview", operation_result.get("status", "unknown"), **operation_result)

    if operation_result.get("status") != "completed":
        payload = _pipeline_report(
            status="failed",
            run_dir=run_dir,
            corpus_root=corpus_root,
            manifest_path=manifest_path,
            generated_manifest_path=generated_manifest_path,
            generated_root=generated_root,
            operation=operation_result,
            benchmark_summary=None,
            calibration=None,
            artifacts=artifacts,
            stages=stages,
            error="organizer Preview did not complete",
        )
        _atomic_json(run_dir / "pipeline-report.json", payload)
        return payload

    if detection_report_path is None or not detection_report_path.is_file():
        payload = _pipeline_report(
            status="failed",
            run_dir=run_dir,
            corpus_root=corpus_root,
            manifest_path=manifest_path,
            generated_manifest_path=generated_manifest_path,
            generated_root=generated_root,
            operation=operation_result,
            benchmark_summary=None,
            calibration=None,
            artifacts=artifacts,
            stages=stages,
            error="Preview completed without a detection-report.json artifact",
        )
        _atomic_json(run_dir / "pipeline-report.json", payload)
        return payload

    detection_copy = run_dir / "detection-report.json"
    shutil.copy2(detection_report_path, detection_copy)
    artifacts["detection_report"] = str(detection_copy)
    detection_csv = detection_report_path.with_suffix(".csv")
    copied_csv = _copy_if_present(detection_csv, run_dir / "detection-report.csv")
    if copied_csv:
        artifacts["detection_csv"] = copied_csv

    announce("evaluate", "started")
    detection_payload = json.loads(detection_copy.read_text(encoding="utf-8"))
    rows = evaluate_detections(
        manifest=manifest,
        samples=samples,
        detection_report=detection_payload,
        corpus_root=corpus_root,
    )
    configuration = {
        "offline": not allow_online,
        "workers": workers,
        "min_confidence": min_confidence,
        "normalize_persian": normalize_persian,
        "manifest_sha256": sha256_file(manifest_path),
        "sample_count": len(samples),
    }
    report = benchmark_report(
        rows,
        benchmark_name=manifest.name,
        avachin_version=AVACHIN_VERSION,
        git_commit=git_commit(),
        configuration=configuration,
    )
    benchmark_json = _atomic_json(run_dir / "benchmark-report.json", report)
    benchmark_csv = _write_evaluation_csv(run_dir / "benchmark-report.csv", rows)
    artifacts["benchmark_json"] = str(benchmark_json)
    artifacts["benchmark_csv"] = str(benchmark_csv)
    announce("evaluate", "completed", **report["summary"])

    announce("calibrate", "started")
    best, safe_profiles = calibrate(rows)
    threshold_payload = calibration_report(
        best,
        safe_profiles,
        avachin_version=AVACHIN_VERSION,
        git_commit=git_commit(),
    )
    threshold_json = _atomic_json(run_dir / "threshold-profile.json", threshold_payload)
    artifacts["threshold_profile"] = str(threshold_json)
    announce(
        "calibrate",
        "completed",
        safe_profile_count=len(safe_profiles),
        best=best.to_dict(),
    )

    gate_passed = bool(report["summary"]["gate_false_auto_apply_zero"])
    status = "passed" if gate_passed else "gate-failed"
    payload = _pipeline_report(
        status=status,
        run_dir=run_dir,
        corpus_root=corpus_root,
        manifest_path=manifest_path,
        generated_manifest_path=generated_manifest_path,
        generated_root=generated_root,
        operation=operation_result,
        benchmark_summary=report["summary"],
        calibration=threshold_payload["best"],
        artifacts=artifacts,
        stages=stages,
    )
    pipeline_json = _atomic_json(run_dir / "pipeline-report.json", payload)
    payload["artifacts"]["pipeline_report"] = str(pipeline_json)
    _atomic_json(pipeline_json, payload)
    return payload


def _default_db_path() -> Path:
    from tools.local_fingerprint_library import local_db_path

    return local_db_path().resolve()
