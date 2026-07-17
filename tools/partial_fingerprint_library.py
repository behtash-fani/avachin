#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manage and test Avachin's Schema V3 partial fingerprint index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import local_fingerprint_library as local_fp  # noqa: E402
from tools import partial_fingerprint_store as partial  # noqa: E402


def print_stats(result: dict[str, int]) -> None:
    print("Local partial fingerprint DB")
    for key in (
        "schema_version",
        "recordings",
        "audio_files",
        "fingerprints",
        "segments",
        "external_ids",
        "artists",
        "legacy_rows_imported",
    ):
        if key in result:
            print(f"  {key}: {result[key]}")
    print(f"  db: {local_fp.local_db_path()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Schema V3 partial fingerprints")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Create and backfill the segment index")
    sub.add_parser("stats", help="Show full and segment fingerprint counts")
    check = sub.add_parser("check", help="Match a clip against local fingerprint segments")
    check.add_argument("--file", type=Path, required=True)
    check.add_argument("--threshold", type=float, default=partial.DEFAULT_PARTIAL_THRESHOLD)
    check.add_argument("--minimum-margin", type=float, default=partial.DEFAULT_MIN_MARGIN)

    args = parser.parse_args()
    try:
        if args.command in {"migrate", "stats"}:
            result = partial.ensure_database()
            print_stats(result)
            return 0

        fpcalc = local_fp.find_fpcalc()
        result = partial.match_file_partial(
            args.file,
            threshold=args.threshold,
            minimum_margin=args.minimum_margin,
            fpcalc_path=fpcalc,
        )
        if not result:
            print("Result: no local partial fingerprint match")
            return 1
        print("Result: LOCAL PARTIAL MATCH")
        print("  source: local_fingerprint")
        print(f"  schema_version: {result['schema_version']}")
        print(f"  recording_id: {result['recording_id']}")
        print(f"  confidence: {result['score']:.2f}")
        print(f"  title: {result['title']}")
        print(f"  artist: {result['artist']}")
        print(f"  album: {result['album'] or '-'}")
        print(f"  query_duration_seconds: {result['query_duration_seconds']}")
        print(
            "  best_reference_segment_seconds: "
            f"{result['segment_start_seconds']} - {result['segment_end_seconds']}"
        )
        print(f"  runner_up_margin: {result['runner_up_margin']}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
