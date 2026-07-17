#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summarize acoustic matches from an Avachin preview report.

The organizer intentionally samples console progress for large libraries. This
helper reads report.csv so local fingerprint acceptance can be verified without
running the full preview a second time.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402

ACOUSTIC_SOURCES = {"local_fingerprint", "acoustid", "audd"}


def latest_report(reports_root: Path | None = None) -> Path | None:
    root = reports_root or (app.app_data_dir() / "reports")
    if not root.exists():
        return None
    reports = [path for path in root.glob("*/report.csv") if path.is_file()]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime_ns)


def read_rows(report_path: Path) -> list[dict[str, str]]:
    with report_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def normalized(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def filter_rows(
    rows: Iterable[dict[str, str]],
    *,
    source: str | None = None,
    contains: str = "",
) -> list[dict[str, str]]:
    source_key = normalized(source)
    query = normalized(contains)
    selected: list[dict[str, str]] = []
    for row in rows:
        if source_key and normalized(row.get("match_source")) != source_key:
            continue
        if query:
            searchable = " | ".join(
                normalized(row.get(field))
                for field in (
                    "source_path",
                    "old_filename",
                    "new_filename",
                    "title",
                    "artist",
                    "album",
                    "final_path",
                )
            )
            if query not in searchable:
                continue
        selected.append(row)
    return selected


def print_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        print("  none")
        return
    for row in rows:
        confidence = str(row.get("confidence") or "-").strip()
        print(
            "  - "
            f"{row.get('title') or '-'} / {row.get('artist') or '-'} "
            f"[{row.get('match_source') or '-'} {confidence}%]"
        )
        print(f"    source: {row.get('source_path') or '-'}")
        print(f"    target: {row.get('final_path') or row.get('new_filename') or '-'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize fingerprint matches from report.csv")
    parser.add_argument("--report", type=Path, help="Specific report.csv path")
    parser.add_argument("--contains", default="", help="Filter by path, filename, title, artist, or album")
    parser.add_argument(
        "--require-local",
        action="store_true",
        help="Return exit code 1 when no local_fingerprint match exists",
    )
    args = parser.parse_args()

    report_path = args.report or latest_report()
    if report_path is None or not report_path.exists():
        print("No Avachin preview report was found.", file=sys.stderr)
        return 2

    rows = read_rows(report_path)
    local_rows = filter_rows(rows, source="local_fingerprint", contains=args.contains)
    acoustic_rows = [
        row for row in filter_rows(rows, contains=args.contains)
        if normalized(row.get("match_source")) in ACOUSTIC_SOURCES
    ]

    print(f"Preview report: {report_path}")
    print(f"Rows: {len(rows)}")
    print(f"Local fingerprint matches: {len(local_rows)}")
    print(f"All acoustic matches: {len(acoustic_rows)}")
    print()
    print("Local fingerprint details:")
    print_rows(local_rows)

    if args.require_local and not local_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
