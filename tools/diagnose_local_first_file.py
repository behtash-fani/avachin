#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose one file across the local fingerprint and preview pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_local_first_launcher as runtime  # noqa: E402
import tools.local_fingerprint_library as local_fp  # noqa: E402
import tools.summarize_preview_fingerprints as preview_summary  # noqa: E402

app = runtime.app
launcher = runtime.launcher


def _print_report_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        print("  none")
        return
    for row in rows:
        print(
            "  - "
            f"{row.get('title') or '-'} / {row.get('artist') or '-'} "
            f"[{row.get('match_source') or '-'} {row.get('confidence') or '-'}%]"
        )
        print(f"    source: {row.get('source_path') or '-'}")
        print(f"    target: {row.get('final_path') or row.get('new_filename') or '-'}")
        if row.get("error"):
            print(f"    error: {row['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose one file in Avachin's local-first pipeline")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="Optional report.csv path")
    args = parser.parse_args()

    file_path = args.file.expanduser().resolve()
    print(f"File: {file_path}")
    print(f"Exists: {file_path.exists()}")
    if not file_path.is_file():
        print("Result: input file was not found", file=sys.stderr)
        return 3

    config = app.load_config(PROJECT_ROOT)
    fpcalc_found = app.find_fpcalc(PROJECT_ROOT)
    fpcalc_path = Path(fpcalc_found) if fpcalc_found else None
    db_path = local_fp.local_db_path()
    db_stats = local_fp.stats()
    threshold = float(config.get("local_fingerprint_match_threshold", 86.0) or 86.0)
    duration_tolerance = float(
        config.get("local_fingerprint_duration_tolerance_seconds", 8.0) or 8.0
    )

    print()
    print("Runtime:")
    print(f"  app version: {app.APP_VERSION}")
    print(f"  local-first patch: {bool(getattr(app.determine_candidate, '__avachin_local_first__', False))}")
    print(f"  local library enabled: {bool(config.get('local_fingerprint_library_enabled', True))}")
    print(f"  threshold: {threshold:.2f}")
    print(f"  duration tolerance: {duration_tolerance:.2f}s")
    print(f"  fpcalc: {fpcalc_path or 'NOT FOUND'}")
    print(f"  database: {db_path}")
    print(f"  database exists: {db_path.exists()}")
    print(f"  database tracks: {db_stats['tracks']}")
    print(f"  database artists: {db_stats['artists']}")

    raw_match = None
    raw_error = None
    try:
        raw_match = local_fp.match_file(
            file_path,
            threshold=threshold,
            duration_tolerance_seconds=duration_tolerance,
            fpcalc_path=fpcalc_path,
        )
    except Exception as exc:  # diagnostic must expose the exact failure
        raw_error = str(exc)

    print()
    print("Direct local matcher:")
    if raw_error:
        print(f"  ERROR: {raw_error}")
    elif raw_match is None:
        print("  NO MATCH")
    else:
        print("  MATCH")
        print(f"  artist: {raw_match.get('artist') or '-'}")
        print(f"  title: {raw_match.get('title') or '-'}")
        print(f"  album: {raw_match.get('album') or '-'}")
        print(f"  score: {raw_match.get('score')}")
        print(f"  fingerprint score: {raw_match.get('fingerprint_score')}")
        print(f"  duration diff: {raw_match.get('duration_diff_seconds')}s")

    candidate, helper_errors = launcher._identify_by_local_fingerprint(
        file_path,
        fpcalc_path,
        config,
    )
    print()
    print("Launcher local resolver:")
    if candidate is None:
        print("  NO CANDIDATE")
    else:
        print("  CANDIDATE")
        print(f"  source: {candidate.source}")
        print(f"  artist: {candidate.artist}")
        print(f"  title: {candidate.title}")
        print(f"  confidence: {candidate.confidence:.2f}")
    for error in helper_errors:
        print(f"  warning: {error}")

    report_path = args.report or preview_summary.latest_report()
    report_matches: list[dict[str, str]] = []
    if report_path and report_path.exists():
        rows = preview_summary.read_rows(report_path)
        report_matches = preview_summary.filter_rows(rows, contains=str(file_path))
        if not report_matches:
            report_matches = preview_summary.filter_rows(rows, contains=file_path.name)
        print()
        print(f"Preview report: {report_path}")
        print("Matching report rows:")
        _print_report_rows(report_matches)
    else:
        print()
        print("Preview report: not found")

    report_local = any(
        preview_summary.normalized(row.get("match_source")) == "local_fingerprint"
        for row in report_matches
    )

    print()
    if candidate is not None and report_local:
        print("Diagnosis: PASS - direct local match and preview local match agree.")
        return 0
    if candidate is not None and not report_local:
        print("Diagnosis: PIPELINE MISMATCH - local resolver matches, but preview did not record it.")
        return 1
    if raw_error:
        print("Diagnosis: LOCAL MATCHER ERROR - fix the reported fpcalc/database error first.")
        return 2
    print("Diagnosis: LOCAL MISS - the current database/threshold did not match this file.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
