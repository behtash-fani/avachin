#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely index a trusted, already-organized MP3 library into Avachin.

The default mode is a read-only preview. ``--apply`` stores Chromaprints in the
local Schema V2 database and then backfills Schema V3 partial-audio segments.
Music files are never renamed, moved, tagged, or otherwise modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402
from tools import local_fingerprint_library as local_fp  # noqa: E402
from tools import partial_fingerprint_store as partial_store  # noqa: E402

UNKNOWN_VALUES = {
    "",
    "-",
    "na",
    "n/a",
    "none",
    "unknown",
    "unknown artist",
    "unknown title",
    "untitled",
    "no title",
    "track",
    "track 1",
}
DEFAULT_SKIPPED_DIRECTORIES = {
    "conflicts",
    "_other_files",
    "_unknown artist",
    "review - non vocal artists",
}
REPORT_FIELDS = (
    "source_path",
    "status",
    "artist",
    "title",
    "album",
    "audio_sha256",
    "recording_id",
    "message",
)


@dataclass
class IndexItem:
    source_path: str
    status: str
    artist: str = ""
    title: str = ""
    album: str = ""
    audio_sha256: str = ""
    recording_id: str = ""
    message: str = ""


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _key(value: Any) -> str:
    return _text(value).casefold()


def _is_unknown(value: Any) -> bool:
    text = _key(value)
    if text in UNKNOWN_VALUES:
        return True
    return any(marker in text for marker in ("unknown artist", "unknown title", "untitled"))


def _path_key(path: Path | str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return str(path).casefold()


def _configured_skipped_directories() -> set[str]:
    names = set(DEFAULT_SKIPPED_DIRECTORIES)
    try:
        config = app.load_config(PROJECT_ROOT)
    except Exception:
        config = {}
    for key in ("duplicates_folder", "other_files_folder", "unknown_artist_folder", "non_vocal_review_folder"):
        value = _key(config.get(key)) if isinstance(config, dict) else ""
        if value:
            names.add(value)
    return names


def scan_mp3_files(root: Path, *, limit: int | None = None) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    skipped = _configured_skipped_directories()
    result: list[Path] = []
    for current_dir, dir_names, file_names in os.walk(root):
        dir_names[:] = sorted(
            name
            for name in dir_names
            if not name.startswith(".")
            and _key(name) not in skipped
            and not (Path(current_dir) / name).is_symlink()
        )
        for name in sorted(file_names):
            path = Path(current_dir) / name
            if path.suffix.casefold() != ".mp3" or path.is_symlink():
                continue
            result.append(path)
            if limit is not None and len(result) >= max(0, int(limit)):
                return result
    return result


def trusted_metadata(file_path: Path) -> tuple[dict[str, str] | None, str]:
    try:
        audio = app.read_mp3(file_path)
    except Exception as exc:
        return None, f"metadata-read-failed: {exc}"
    tags = getattr(audio, "tags", None)
    if tags is None:
        return None, "missing-tags"

    artist = _text(getattr(tags, "artist", "")) or _text(getattr(tags, "albumartist", ""))
    title = _text(getattr(tags, "title", ""))
    album = _text(getattr(tags, "album", ""))

    if _is_unknown(artist) or _is_unknown(title):
        return None, "missing-or-placeholder-title-artist"
    try:
        if not app.meaningful_artist_label(artist):
            return None, "artist-label-not-meaningful"
    except Exception:
        if len(artist) < 2:
            return None, "artist-label-too-short"

    site_pattern = getattr(app, "SITE_OR_SOURCE_RE", None)
    if site_pattern is not None:
        if site_pattern.search(artist) or site_pattern.search(title):
            return None, "source-or-website-noise-in-tags"

    return {"artist": artist, "title": title, "album": album}, "trusted-tags"


def existing_inventory(db_path: Path) -> tuple[set[str], set[str]]:
    db_path = Path(db_path)
    if not db_path.exists():
        return set(), set()
    conn = sqlite3.connect(str(db_path))
    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audio_files'"
        ).fetchone()
        if table is None:
            return set(), set()
        rows = conn.execute("SELECT source_path, audio_sha256 FROM audio_files").fetchall()
    finally:
        conn.close()
    paths = {_path_key(row[0]) for row in rows if row[0]}
    hashes = {str(row[1]).strip() for row in rows if row[1]}
    return paths, hashes


def backup_database(db_path: Path, backup_root: Path | None = None) -> Path | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    backup_root = Path(backup_root) if backup_root else db_path.parent / "fingerprint_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = backup_root / f"local_fingerprint_library_{stamp}.sqlite3"
    source_conn = sqlite3.connect(str(db_path))
    target_conn = sqlite3.connect(str(destination))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()
    return destination


def default_report_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = app.app_data_dir() / "bulk_index_reports" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_reports(report_dir: Path, items: Iterable[IndexItem], summary: dict[str, Any]) -> tuple[Path, Path]:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / "report.csv"
    json_path = report_dir / "summary.json"
    rows = [asdict(item) for item in items]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def index_library(
    root: Path,
    *,
    apply: bool = False,
    limit: int | None = None,
    db_path: Path | None = None,
    report_dir: Path | None = None,
    fpcalc_path: Path | None = None,
    progress_every: int = 25,
    learn_file_func: Callable[..., dict[str, Any]] | None = None,
    hash_file_func: Callable[[Path], str] | None = None,
    segment_backfill_func: Callable[[Path | None], dict[str, int]] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    db_path = Path(db_path) if db_path else local_fp.local_db_path()
    report_dir = Path(report_dir) if report_dir else default_report_dir()
    learn_file_func = learn_file_func or local_fp.learn_file
    hash_file_func = hash_file_func or local_fp.audio_sha256
    segment_backfill_func = segment_backfill_func or partial_store.ensure_database

    files = scan_mp3_files(root, limit=limit)
    existing_paths, existing_hashes = existing_inventory(db_path)
    items: list[IndexItem] = []
    candidates: list[tuple[Path, dict[str, str], IndexItem]] = []

    for index, path in enumerate(files, start=1):
        metadata, reason = trusted_metadata(path)
        if metadata is None:
            items.append(IndexItem(source_path=str(path), status="skipped", message=reason))
        elif _path_key(path) in existing_paths:
            items.append(
                IndexItem(
                    source_path=str(path),
                    status="already-indexed-path",
                    artist=metadata["artist"],
                    title=metadata["title"],
                    album=metadata["album"],
                    message="database already contains this source path",
                )
            )
        else:
            item = IndexItem(
                source_path=str(path),
                status="eligible" if not apply else "pending",
                artist=metadata["artist"],
                title=metadata["title"],
                album=metadata["album"],
                message=reason,
            )
            items.append(item)
            candidates.append((path, metadata, item))
        if progress_every > 0 and index % progress_every == 0:
            print(f"  Metadata scan: {index}/{len(files)}")

    backup_path: Path | None = None
    indexed = 0
    segment_stats: dict[str, int] | None = None
    seen_hashes = set(existing_hashes)

    if apply and candidates:
        backup_path = backup_database(db_path)
        fpcalc_path = fpcalc_path or local_fp.find_fpcalc()
        for index, (path, metadata, item) in enumerate(candidates, start=1):
            try:
                audio_hash = str(hash_file_func(path)).strip()
                item.audio_sha256 = audio_hash
                if audio_hash and audio_hash in seen_hashes:
                    item.status = "duplicate-audio-skipped"
                    item.message = "identical audio already exists in local database or this batch"
                    continue
                learned = learn_file_func(
                    path,
                    artist=metadata["artist"],
                    title=metadata["title"],
                    album=metadata["album"],
                    source="bulk-index:trusted-tags",
                    confidence=98.0,
                    fpcalc_path=fpcalc_path,
                    db_path=db_path,
                )
                item.status = "indexed"
                item.recording_id = str(learned.get("recording_id") or "")
                item.audio_sha256 = str(learned.get("audio_sha256") or audio_hash)
                item.message = "fingerprint stored"
                indexed += 1
                if audio_hash:
                    seen_hashes.add(audio_hash)
            except Exception as exc:
                item.status = "error"
                item.message = str(exc)
            if progress_every > 0 and index % progress_every == 0:
                print(f"  Fingerprint index: {index}/{len(candidates)}")

        if indexed:
            try:
                segment_stats = segment_backfill_func(db_path)
            except Exception as exc:
                segment_stats = {"error": str(exc)}  # type: ignore[dict-item]

    counts = Counter(item.status for item in items)
    summary: dict[str, Any] = {
        "mode": "apply" if apply else "preview",
        "root": str(root),
        "db_path": str(db_path),
        "files_scanned": len(files),
        "eligible": len(candidates),
        "indexed": indexed,
        "counts": dict(sorted(counts.items())),
        "backup_path": str(backup_path) if backup_path else "",
        "segment_stats": segment_stats or {},
        "report_dir": str(report_dir),
    }
    csv_path, json_path = write_reports(report_dir, items, summary)
    summary["csv_report"] = str(csv_path)
    summary["json_report"] = str(json_path)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print(f"Bulk local fingerprint index: {str(summary['mode']).upper()}")
    print(f"MP3 files scanned: {summary['files_scanned']}")
    print(f"Eligible trusted-tag files: {summary['eligible']}")
    print(f"Fingerprints indexed: {summary['indexed']}")
    for status, count in summary.get("counts", {}).items():
        print(f"  {status}: {count}")
    if summary.get("backup_path"):
        print(f"Database backup: {summary['backup_path']}")
    segment_stats = summary.get("segment_stats") or {}
    if segment_stats:
        if segment_stats.get("error"):
            print(f"Segment backfill warning: {segment_stats['error']}")
        else:
            print(f"Schema version: {segment_stats.get('schema_version', '-')}")
            print(f"Local segments: {segment_stats.get('segments', '-')}")
    print(f"CSV report: {summary['csv_report']}")
    print(f"JSON summary: {summary['json_report']}")
    if summary["mode"] == "preview":
        print("\nNo fingerprint was stored. Run again with --apply after reviewing the report.")
    else:
        print("\nNo music file was changed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview or safely index an already-organized MP3 library into Avachin's local database."
    )
    parser.add_argument("--root", type=Path, help="Root folder of the organized MP3 library")
    parser.add_argument("--apply", action="store_true", help="Store eligible fingerprints after creating a DB backup")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N MP3 files")
    parser.add_argument("--db", type=Path, default=None, help="Optional SQLite database path")
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    root = args.root
    if root is None:
        raw = input("Organized music library folder path: ").strip().strip('"')
        root = Path(raw)
    try:
        summary = index_library(
            root,
            apply=bool(args.apply),
            limit=args.limit,
            db_path=args.db,
            report_dir=args.report_dir,
            progress_every=args.progress_every,
        )
        print_summary(summary)
        return 1 if summary.get("counts", {}).get("error", 0) else 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
