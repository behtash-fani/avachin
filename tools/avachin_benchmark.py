#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin reference-corpus generation, evaluation and threshold calibration."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_bootstrap import bootstrap_manifest  # noqa: E402
from tools.benchmark_contract import (  # noqa: E402
    BenchmarkManifest,
    generated_samples,
    write_generated_manifest,
)
from tools.benchmark_metrics import (  # noqa: E402
    EvaluationRow,
    benchmark_report,
    evaluate_detections,
    load_generated_samples,
)
from tools.benchmark_thresholds import (  # noqa: E402
    calibrate,
    calibration_report,
)
from tools.benchmark_transforms import materialize_all  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402

DEFAULT_MANIFEST = PROJECT_ROOT / "benchmark" / "manifest.json"
DEFAULT_GENERATED_MANIFEST = PROJECT_ROOT / "benchmark" / "generated-manifest.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "benchmark"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)
    return path


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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


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


def _rows_from_report(payload: Mapping[str, Any]) -> list[EvaluationRow]:
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("benchmark report requires rows")
    result: list[EvaluationRow] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        result.append(
            EvaluationRow(
                sample_id=str(raw.get("sample_id") or ""),
                expected_recording_id=str(raw.get("expected_recording_id") or ""),
                predicted_recording_id=str(raw.get("predicted_recording_id") or ""),
                transform_id=str(raw.get("transform_id") or ""),
                transform_kind=str(raw.get("transform_kind") or ""),
                split=str(raw.get("split") or ""),
                version=str(raw.get("version") or ""),
                hard_negative_group=str(raw.get("hard_negative_group") or ""),
                decision=str(raw.get("decision") or "REJECT"),
                provider=str(raw.get("provider") or ""),
                match_mode=str(raw.get("match_mode") or ""),
                correct=bool(raw.get("correct")),
                identified=bool(raw.get("identified")),
                auto_apply=bool(raw.get("auto_apply")),
                false_auto_apply=bool(raw.get("false_auto_apply")),
                audio_confidence=(
                    float(raw["audio_confidence"])
                    if raw.get("audio_confidence") is not None
                    else None
                ),
                metadata_confidence=(
                    float(raw["metadata_confidence"])
                    if raw.get("metadata_confidence") is not None
                    else None
                ),
                identity_confidence=(
                    float(raw["identity_confidence"])
                    if raw.get("identity_confidence") is not None
                    else None
                ),
                overall_confidence=(
                    float(raw["overall_confidence"])
                    if raw.get("overall_confidence") is not None
                    else None
                ),
                candidate_margin=(
                    float(raw["candidate_margin"])
                    if raw.get("candidate_margin") is not None
                    else None
                ),
                query_seconds=(
                    float(raw["query_seconds"])
                    if raw.get("query_seconds") is not None
                    else None
                ),
                expected_identity_keys=tuple(raw.get("expected_identity_keys") or []),
                predicted_identity_keys=tuple(raw.get("predicted_identity_keys") or []),
            )
        )
    return result


def command_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    else:
        from tools.local_fingerprint_library import local_db_path

        db_path = local_db_path().resolve()
    corpus_root = Path(args.corpus_root).expanduser().resolve()
    return bootstrap_manifest(
        db_path=db_path,
        corpus_root=corpus_root,
        output_manifest=Path(args.output_manifest).expanduser(),
        limit=int(args.limit),
        minimum_duration_seconds=float(args.minimum_duration),
        validation_percent=int(args.validation_percent),
        seed=int(args.seed),
    )


def command_validate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = BenchmarkManifest.load(Path(args.manifest))
    hard_groups = sorted(
        {
            item.hard_negative_group
            for item in manifest.references
            if item.hard_negative_group
        }
    )
    return {
        "status": "valid",
        "schema_version": manifest.schema_version,
        "name": manifest.name,
        "seed": manifest.seed,
        "references": len(manifest.references),
        "transforms": len(manifest.transforms),
        "planned_samples": len(manifest.references) * len(manifest.transforms),
        "hard_negative_groups": hard_groups,
        "identity_keys": len(manifest.identity_owner_map()),
        "ambiguous_identity_keys": list(manifest.ambiguous_identity_keys()),
    }


def command_generate(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.manifest).resolve()
    manifest = BenchmarkManifest.load(manifest_path)
    corpus_root = Path(args.corpus_root or manifest_path.parent).resolve()
    samples = generated_samples(manifest, generated_root=args.generated_root)
    output_manifest = Path(args.output_manifest).resolve()
    write_generated_manifest(output_manifest, manifest, samples)
    commands = []
    if not args.plan_only:
        ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
        if not ffmpeg:
            raise FileNotFoundError("ffmpeg was not found")
        commands = materialize_all(
            samples=samples,
            references=manifest.references,
            transforms=manifest.transforms,
            corpus_root=corpus_root,
            ffmpeg=str(ffmpeg),
            global_seed=manifest.seed,
        )
    return {
        "status": "planned" if args.plan_only else "generated",
        "manifest": str(output_manifest),
        "corpus_root": str(corpus_root),
        "samples": len(samples),
        "materialized": len(commands),
        "seed": manifest.seed,
    }


def command_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = BenchmarkManifest.load(Path(args.manifest))
    _, samples = load_generated_samples(Path(args.generated_manifest))
    detection_report = _load_json(Path(args.detection_report))
    rows = evaluate_detections(
        manifest=manifest,
        samples=samples,
        detection_report=detection_report,
        corpus_root=Path(args.corpus_root),
    )
    configuration = _load_json(Path(args.config)) if args.config else {}
    report = benchmark_report(
        rows,
        benchmark_name=manifest.name,
        avachin_version=AVACHIN_VERSION,
        git_commit=_git_commit(),
        configuration=configuration,
    )
    report_dir = Path(args.report_dir).resolve()
    json_path = _atomic_json(report_dir / "benchmark-report.json", report)
    csv_path = _write_evaluation_csv(report_dir / "benchmark-report.csv", rows)
    return {
        "status": "passed" if report["summary"]["gate_false_auto_apply_zero"] else "failed",
        "json_report": str(json_path),
        "csv_report": str(csv_path),
        "summary": report["summary"],
    }


def command_calibrate(args: argparse.Namespace) -> dict[str, Any]:
    benchmark = _load_json(Path(args.benchmark_report))
    rows = _rows_from_report(benchmark)
    best, safe_profiles = calibrate(rows)
    report = calibration_report(
        best,
        safe_profiles,
        avachin_version=AVACHIN_VERSION,
        git_commit=_git_commit(),
    )
    output = _atomic_json(Path(args.output).resolve(), report)
    return {
        "status": "calibrated",
        "output": str(output),
        "best": report["best"],
        "safe_profile_count": report["safe_profile_count"],
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Build and score Avachin's repeatable audio benchmark corpus."
    )
    commands = root.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser(
        "bootstrap",
        help="Copy trusted references from the local fingerprint DB into a reviewable corpus.",
    )
    bootstrap.add_argument("--db")
    bootstrap.add_argument("--corpus-root", default=str(PROJECT_ROOT / "benchmark"))
    bootstrap.add_argument("--output-manifest", default=str(DEFAULT_MANIFEST))
    bootstrap.add_argument("--limit", type=int, default=100)
    bootstrap.add_argument("--minimum-duration", type=float, default=20.0)
    bootstrap.add_argument("--validation-percent", type=int, default=80)
    bootstrap.add_argument("--seed", type=int, default=20260718)

    validate = commands.add_parser("validate", help="Validate the trusted reference manifest.")
    validate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))

    generate = commands.add_parser("generate", help="Plan or materialize deterministic audio transforms.")
    generate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    generate.add_argument("--corpus-root")
    generate.add_argument("--generated-root", default="generated")
    generate.add_argument("--output-manifest", default=str(DEFAULT_GENERATED_MANIFEST))
    generate.add_argument("--ffmpeg")
    generate.add_argument("--plan-only", action="store_true")

    evaluate = commands.add_parser("evaluate", help="Evaluate a DetectionResult report against expected identities.")
    evaluate.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    evaluate.add_argument("--generated-manifest", default=str(DEFAULT_GENERATED_MANIFEST))
    evaluate.add_argument("--detection-report", required=True)
    evaluate.add_argument("--corpus-root", required=True)
    evaluate.add_argument("--config")
    evaluate.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))

    calibrate_parser = commands.add_parser(
        "calibrate", help="Find the best zero-False-Auto-Apply threshold profile."
    )
    calibrate_parser.add_argument(
        "--benchmark-report",
        default=str(DEFAULT_REPORT_DIR / "benchmark-report.json"),
    )
    calibrate_parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT_DIR / "threshold-profile.json"),
    )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            result = command_bootstrap(args)
        elif args.command == "validate":
            result = command_validate(args)
        elif args.command == "generate":
            result = command_generate(args)
        elif args.command == "evaluate":
            result = command_evaluate(args)
        else:
            result = command_calibrate(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
