#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Chromaprint fingerprint library for Avachin.

The public API remains compatible with the original V1 tool, while storage now
uses the versioned V2 model:

- one ``recording`` represents the musical identity;
- one recording can have multiple physical ``audio_files``;
- each audio file can have multiple algorithm/version ``fingerprints``;
- provider identifiers are stored independently in ``external_ids``.

Existing ``local_fingerprints`` rows are migrated non-destructively.  The old
table is intentionally retained for rollback and audit purposes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402
from tools import fingerprint_store_v2 as store  # noqa: E402

DB_FILENAME = "local_fingerprint_library.sqlite3"
UNKNOWN_VALUES = {
    "",
    "-",
    "unknown",
    "unknown artist",
    "untitled",
    "no title",
    "track",
    "track 1",
}


def _safe_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _clean_optional(value: Any) -> str:
    text = _safe_text(value)
    return "" if text.lower() in UNKNOWN_VALUES else text


def local_db_path() -> Path:
    base = app.app_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / DB_FILENAME


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else local_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    store.ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> dict[str, int]:
    """Compatibility wrapper used by older callers and tests."""
    return store.ensure_schema(conn)


def find_fpcalc(project_root: Path = PROJECT_ROOT) -> Path:
    fpcalc = app.find_fpcalc(project_root)
    if fpcalc is None:
        raise RuntimeError("fpcalc was not found. Put fpcalc.exe in tools\\fpcalc.exe or install it in PATH.")
    return Path(fpcalc)


def _parse_raw_fingerprint(value: Any) -> list[int]:
    if isinstance(value, list):
        return [int(item) for item in value]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        loaded = json.loads(text)
        if isinstance(loaded, list):
            return [int(item) for item in loaded]
    return [int(part.strip()) for part in text.split(",") if part.strip()]


def raw_fingerprint(
    file_path: Path,
    fpcalc_path: Path | None = None,
    timeout: int = 120,
) -> tuple[float, list[int]]:
    fpcalc = fpcalc_path or find_fpcalc(PROJECT_ROOT)
    command = [str(fpcalc), "-raw", "-json", str(file_path)]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode != 0:
        stderr = " ".join((completed.stderr or completed.stdout or "").split())
        raise RuntimeError(f"fpcalc failed: {stderr[:700]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"fpcalc returned invalid JSON: {exc}") from exc

    duration = float(payload.get("duration") or 0.0)
    fingerprint = _parse_raw_fingerprint(payload.get("fingerprint"))
    if not fingerprint:
        raise RuntimeError("fpcalc returned an empty fingerprint")
    return duration, fingerprint


def fingerprint_sha256(fingerprint: list[int]) -> str:
    payload = json.dumps(fingerprint, separators=(",", ":"))
    return app.hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audio_sha256(file_path: Path) -> str:
    try:
        return app.hash_file(file_path)
    except Exception:
        digest = app.hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _metadata_from_tags(file_path: Path) -> dict[str, str]:
    try:
        audio = app.read_mp3(file_path)
    except Exception:
        return {"artist": "", "title": "", "album": ""}
    tags = audio.tags
    return {
        "artist": _clean_optional(getattr(tags, "artist", ""))
        or _clean_optional(getattr(tags, "albumartist", "")),
        "title": _clean_optional(getattr(tags, "title", "")),
        "album": _clean_optional(getattr(tags, "album", "")),
    }


def learn_file(
    file_path: Path,
    artist: str = "",
    title: str = "",
    album: str = "",
    source: str = "manual",
    confidence: float = 100.0,
    fpcalc_path: Path | None = None,
    db_path: Path | None = None,
    external_ids: Iterable[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    """Learn one encoding while reusing the shared recording identity."""
    file_path = Path(file_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(str(file_path))

    tags = _metadata_from_tags(file_path)
    artist = _clean_optional(artist) or tags["artist"]
    title = _clean_optional(title) or tags["title"]
    album = _clean_optional(album) or tags["album"]
    if not artist or not title:
        raise RuntimeError("artist and title are required when the file tags are not reliable")

    duration, fingerprint = raw_fingerprint(file_path, fpcalc_path=fpcalc_path)
    fp_sha = fingerprint_sha256(fingerprint)
    au_sha = audio_sha256(file_path)
    raw_json = json.dumps(fingerprint, separators=(",", ":"))

    conn = connect(db_path)
    try:
        with conn:
            recording_id = store.upsert_recording(
                conn,
                artist=artist,
                title=title,
                album=album,
                source=_safe_text(source) or "manual",
                confidence=float(confidence),
            )
            audio_file_id = store.upsert_audio_file(
                conn,
                recording_id=recording_id,
                audio_sha256=au_sha,
                source_path=str(file_path),
                duration_seconds=duration,
            )
            fingerprint_id = store.replace_fingerprint(
                conn,
                recording_id=recording_id,
                audio_file_id=audio_file_id,
                fingerprint_sha256=fp_sha,
                fingerprint_frames=len(fingerprint),
                raw_fingerprint_json=raw_json,
                duration_seconds=duration,
                source=_safe_text(source) or "manual",
                confidence=float(confidence),
            )
            identifiers_added = store.add_external_ids(conn, recording_id, external_ids)
    finally:
        conn.close()

    return {
        "id": fingerprint_id,
        "recording_id": recording_id,
        "audio_file_id": audio_file_id,
        "artist": artist,
        "title": title,
        "album": album,
        "duration_seconds": duration,
        "fingerprint_frames": len(fingerprint),
        "audio_sha256": au_sha,
        "fingerprint_sha256": fp_sha,
        "external_ids_added": identifiers_added,
        "schema_version": store.SCHEMA_VERSION,
        "db_path": str(db_path or local_db_path()),
    }


def _bit_similarity(left: int, right: int) -> float:
    return 1.0 - (((left ^ right) & 0xFFFFFFFF).bit_count() / 32.0)


def fingerprint_similarity(left: list[int], right: list[int], max_offset: int = 12) -> float:
    if not left or not right:
        return 0.0
    shortest = min(len(left), len(right))
    if shortest < 20:
        return 0.0

    sample_step = max(1, shortest // 1500)
    best = 0.0
    for offset in range(-max_offset, max_offset + 1):
        left_start = max(0, offset)
        right_start = max(0, -offset)
        overlap = min(len(left) - left_start, len(right) - right_start)
        if overlap <= 0:
            continue
        total = 0.0
        count = 0
        for pos in range(0, overlap, sample_step):
            total += _bit_similarity(left[left_start + pos], right[right_start + pos])
            count += 1
        if not count:
            continue
        bit_score = (total / count) * 100.0
        coverage = (overlap / max(len(left), len(right))) * 100.0
        score = (bit_score * 0.92) + (coverage * 0.08)
        if score > best:
            best = score
    return best


def _row_to_candidate(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "recording_id": row["recording_id"],
        "audio_file_id": row["audio_file_id"],
        "algorithm": row["algorithm"],
        "algorithm_version": row["algorithm_version"],
        "artist": row["artist"],
        "title": row["title"],
        "album": row["album"] or "",
        "duration_seconds": row["duration_seconds"],
        "fingerprint_frames": row["fingerprint_frames"],
        "source": row["source"],
        "source_path": row["source_path"] or "",
        "audio_sha256": row["audio_sha256"] or "",
    }


def match_file(
    file_path: Path,
    threshold: float = 86.0,
    duration_tolerance_seconds: float = 8.0,
    fpcalc_path: Path | None = None,
    db_path: Path | None = None,
    max_candidates: int = 5000,
) -> dict[str, Any] | None:
    file_path = Path(file_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(str(file_path))

    duration, fingerprint = raw_fingerprint(file_path, fpcalc_path=fpcalc_path)
    conn = connect(db_path)
    try:
        rows = store.candidate_rows(
            conn,
            duration_seconds=duration,
            tolerance_seconds=float(duration_tolerance_seconds),
            max_candidates=int(max_candidates),
        )
    finally:
        conn.close()

    best: dict[str, Any] | None = None
    for row in rows:
        try:
            stored = _parse_raw_fingerprint(row["raw_fingerprint_json"])
        except Exception:
            continue
        fp_score = fingerprint_similarity(fingerprint, stored)
        duration_diff = abs(float(row["duration_seconds"] or 0.0) - duration)
        duration_score = max(
            0.0,
            100.0
            - (duration_diff / max(1.0, duration_tolerance_seconds) * 100.0),
        )
        score = (fp_score * 0.96) + (duration_score * 0.04)
        candidate = _row_to_candidate(row)
        candidate.update(
            {
                "score": round(score, 2),
                "fingerprint_score": round(fp_score, 2),
                "duration_score": round(duration_score, 2),
                "duration_diff_seconds": round(duration_diff, 2),
                "query_duration_seconds": round(duration, 2),
                "query_fingerprint_frames": len(fingerprint),
                "schema_version": store.SCHEMA_VERSION,
            }
        )
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if best is not None and float(best["score"]) >= float(threshold):
        return best
    return None


def stats(db_path: Path | None = None) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        result: dict[str, Any] = store.stats(conn)
    finally:
        conn.close()
    result["tracks"] = result["fingerprints"]
    result["db_path"] = str(db_path or local_db_path())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Learn and check Avachin local audio fingerprints.")
    sub = parser.add_subparsers(dest="command", required=True)

    learn = sub.add_parser("learn", help="Store one correctly identified track in the local fingerprint DB.")
    learn.add_argument("--file", type=Path, required=True)
    learn.add_argument("--artist", default="")
    learn.add_argument("--title", default="")
    learn.add_argument("--album", default="")
    learn.add_argument("--source", default="manual")

    check = sub.add_parser("check", help="Check one file against the local fingerprint DB only.")
    check.add_argument("--file", type=Path, required=True)
    check.add_argument("--threshold", type=float, default=86.0)
    check.add_argument("--duration-tolerance", type=float, default=8.0)

    sub.add_parser("stats", help="Show recording/file/fingerprint database statistics.")
    sub.add_parser("migrate", help="Create Schema V2 and migrate any remaining V1 rows.")

    args = parser.parse_args()
    try:
        if args.command == "learn":
            fpcalc = find_fpcalc(PROJECT_ROOT)
            result = learn_file(
                args.file,
                artist=args.artist,
                title=args.title,
                album=args.album,
                source=args.source,
                fpcalc_path=fpcalc,
            )
            print("Local fingerprint learned")
            print(f"  schema_version: {result['schema_version']}")
            print(f"  recording_id: {result['recording_id']}")
            print(f"  audio_file_id: {result['audio_file_id']}")
            print(f"  artist: {result['artist']}")
            print(f"  title: {result['title']}")
            print(f"  album: {result['album'] or '-'}")
            print(f"  duration: {round(result['duration_seconds'], 2)} seconds")
            print(f"  frames: {result['fingerprint_frames']}")
            print(f"  db: {result['db_path']}")
            return 0

        if args.command == "check":
            fpcalc = find_fpcalc(PROJECT_ROOT)
            result = match_file(
                args.file,
                threshold=args.threshold,
                duration_tolerance_seconds=args.duration_tolerance,
                fpcalc_path=fpcalc,
            )
            if not result:
                print("Result: no local fingerprint match")
                return 1
            print("Result: LOCAL MATCH")
            print("  source: local_fingerprint")
            print(f"  schema_version: {result['schema_version']}")
            print(f"  recording_id: {result['recording_id']}")
            print(f"  confidence: {result['score']:.2f}")
            print(f"  title: {result['title']}")
            print(f"  artist: {result['artist']}")
            print(f"  album: {result['album'] or '-'}")
            print(f"  fingerprint_score: {result['fingerprint_score']}")
            print(f"  duration_diff_seconds: {result['duration_diff_seconds']}")
            return 0

        result = stats()
        if args.command == "migrate":
            print("Local fingerprint DB migration complete")
        else:
            print("Local fingerprint DB")
        print(f"  schema_version: {result['schema_version']}")
        print(f"  recordings: {result['recordings']}")
        print(f"  audio_files: {result['audio_files']}")
        print(f"  fingerprints: {result['fingerprints']}")
        print(f"  external_ids: {result['external_ids']}")
        print(f"  artists: {result['artists']}")
        print(f"  legacy_rows_imported: {result['legacy_rows_imported']}")
        print(f"  db: {result['db_path']}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
