#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema V3 segment index for partial and mid-song local recognition.

The existing full Chromaprint remains the source of truth. This module derives
small overlapping fingerprint windows and stores only integer fingerprints,
never audio. Existing Schema V2 databases are upgraded non-destructively.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from tools import fingerprint_store_v2 as v2_store
from tools import local_fingerprint_library as local_fp

SCHEMA_VERSION = 3
DEFAULT_WINDOW_SECONDS = 24.0
DEFAULT_HOP_SECONDS = 8.0
DEFAULT_MIN_SEGMENT_SECONDS = 12.0
DEFAULT_PARTIAL_THRESHOLD = 84.0
DEFAULT_MIN_MARGIN = 2.0


def _segment_hash(values: list[int]) -> str:
    payload = json.dumps(values, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def segment_windows(
    fingerprint: list[int],
    duration_seconds: float,
    *,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    hop_seconds: float = DEFAULT_HOP_SECONDS,
    min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
) -> list[dict[str, Any]]:
    """Split one raw fingerprint into overlapping time-aware windows."""
    total_frames = len(fingerprint)
    duration = float(duration_seconds or 0.0)
    if total_frames < 20 or duration <= 0:
        return []

    frames_per_second = total_frames / duration
    window_frames = max(20, int(round(float(window_seconds) * frames_per_second)))
    hop_frames = max(1, int(round(float(hop_seconds) * frames_per_second)))
    minimum_frames = max(20, int(round(float(min_segment_seconds) * frames_per_second)))

    if total_frames <= window_frames:
        starts = [0]
    else:
        last_start = total_frames - window_frames
        starts = list(range(0, last_start + 1, hop_frames))
        if starts[-1] != last_start:
            starts.append(last_start)

    result: list[dict[str, Any]] = []
    for start in starts:
        end = min(total_frames, start + window_frames)
        values = fingerprint[start:end]
        if len(values) < minimum_frames:
            continue
        result.append(
            {
                "start_frame": start,
                "end_frame": end,
                "start_seconds": start / frames_per_second,
                "end_seconds": end / frames_per_second,
                "frame_count": len(values),
                "raw_segment_json": json.dumps(values, separators=(",", ":")),
                "segment_sha256": _segment_hash(values),
            }
        )
    return result


def ensure_segment_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fingerprint_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint_id INTEGER NOT NULL REFERENCES fingerprints(id) ON DELETE CASCADE,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            audio_file_id INTEGER NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
            start_frame INTEGER NOT NULL,
            end_frame INTEGER NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            frame_count INTEGER NOT NULL,
            segment_sha256 TEXT NOT NULL,
            raw_segment_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(fingerprint_id, start_frame, end_frame)
        );

        CREATE INDEX IF NOT EXISTS idx_fp_segments_recording
            ON fingerprint_segments(recording_id);
        CREATE INDEX IF NOT EXISTS idx_fp_segments_fingerprint
            ON fingerprint_segments(fingerprint_id);
        CREATE INDEX IF NOT EXISTS idx_fp_segments_frames
            ON fingerprint_segments(frame_count);
        CREATE INDEX IF NOT EXISTS idx_fp_segments_hash
            ON fingerprint_segments(segment_sha256);
        """
    )
    v2_store.set_meta(conn, v2_store.SCHEMA_VERSION_KEY, SCHEMA_VERSION)


def replace_segments_for_fingerprint(
    conn: sqlite3.Connection,
    fingerprint_id: int,
    *,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    hop_seconds: float = DEFAULT_HOP_SECONDS,
    min_segment_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
) -> int:
    row = conn.execute(
        """
        SELECT id, recording_id, audio_file_id, duration_seconds, raw_fingerprint_json
        FROM fingerprints
        WHERE id = ?
        """,
        (int(fingerprint_id),),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"fingerprint not found: {fingerprint_id}")

    try:
        raw = local_fp._parse_raw_fingerprint(row["raw_fingerprint_json"])
    except Exception as exc:
        raise RuntimeError(f"invalid stored fingerprint {fingerprint_id}: {exc}") from exc

    windows = segment_windows(
        raw,
        float(row["duration_seconds"] or 0.0),
        window_seconds=window_seconds,
        hop_seconds=hop_seconds,
        min_segment_seconds=min_segment_seconds,
    )
    conn.execute("DELETE FROM fingerprint_segments WHERE fingerprint_id = ?", (int(fingerprint_id),))
    timestamp = v2_store.now_utc()
    for item in windows:
        conn.execute(
            """
            INSERT INTO fingerprint_segments (
                fingerprint_id, recording_id, audio_file_id,
                start_frame, end_frame, start_seconds, end_seconds,
                frame_count, segment_sha256, raw_segment_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(fingerprint_id),
                str(row["recording_id"]),
                int(row["audio_file_id"]),
                int(item["start_frame"]),
                int(item["end_frame"]),
                float(item["start_seconds"]),
                float(item["end_seconds"]),
                int(item["frame_count"]),
                str(item["segment_sha256"]),
                str(item["raw_segment_json"]),
                timestamp,
            ),
        )
    return len(windows)


def backfill_missing_segments(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT fp.id
        FROM fingerprints AS fp
        LEFT JOIN fingerprint_segments AS seg ON seg.fingerprint_id = fp.id
        GROUP BY fp.id
        HAVING COUNT(seg.id) = 0
        ORDER BY fp.id
        """
    ).fetchall()
    created = 0
    for row in rows:
        created += replace_segments_for_fingerprint(conn, int(row["id"]))
    if rows:
        v2_store.set_meta(conn, "segment_v3_last_backfill_at", v2_store.now_utc())
    return created


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else local_fp.local_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    v2_store.ensure_schema(conn)
    ensure_segment_schema(conn)
    backfill_missing_segments(conn)
    conn.commit()
    return conn


def ensure_database(db_path: Path | None = None) -> dict[str, int]:
    conn = connect(db_path)
    try:
        return stats(conn)
    finally:
        conn.close()


def segment_candidate_rows(conn: sqlite3.Connection, max_candidates: int = 30000) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            seg.id AS segment_id,
            seg.fingerprint_id,
            seg.recording_id,
            seg.audio_file_id,
            seg.start_seconds,
            seg.end_seconds,
            seg.frame_count,
            seg.raw_segment_json,
            rec.artist,
            rec.title,
            rec.album,
            rec.source,
            rec.confidence,
            af.source_path,
            af.audio_sha256
        FROM fingerprint_segments AS seg
        JOIN recordings AS rec ON rec.id = seg.recording_id
        JOIN audio_files AS af ON af.id = seg.audio_file_id
        ORDER BY rec.confidence DESC, seg.id ASC
        LIMIT ?
        """,
        (int(max_candidates),),
    ).fetchall()


def _bit_similarity(left: int, right: int) -> float:
    return 1.0 - (((left ^ right) & 0xFFFFFFFF).bit_count() / 32.0)


def partial_similarity(
    query: list[int],
    reference: list[int],
    *,
    minimum_overlap_frames: int = 64,
) -> float:
    """Best local alignment score for a clip inside a stored segment."""
    if not query or not reference:
        return 0.0

    trim = min(6, max(0, len(query) // 25))
    if len(query) - (trim * 2) >= minimum_overlap_frames:
        query = query[trim : len(query) - trim]

    minimum_overlap = max(minimum_overlap_frames, int(round(len(query) * 0.72)))
    if min(len(query), len(reference)) < minimum_overlap:
        return 0.0

    first_offset = -(len(query) - minimum_overlap)
    last_offset = len(reference) - minimum_overlap
    best = 0.0
    for offset in range(first_offset, last_offset + 1):
        query_start = max(0, -offset)
        reference_start = max(0, offset)
        overlap = min(len(query) - query_start, len(reference) - reference_start)
        if overlap < minimum_overlap:
            continue
        step = max(1, overlap // 320)
        total = 0.0
        count = 0
        for index in range(0, overlap, step):
            total += _bit_similarity(
                query[query_start + index],
                reference[reference_start + index],
            )
            count += 1
        if not count:
            continue
        bit_score = (total / count) * 100.0
        coverage = overlap / max(1, len(query))
        score = bit_score * (0.88 + (0.12 * coverage))
        if score > best:
            best = score
    return best


def match_file_partial(
    file_path: Path,
    *,
    threshold: float = DEFAULT_PARTIAL_THRESHOLD,
    minimum_margin: float = DEFAULT_MIN_MARGIN,
    minimum_clip_seconds: float = DEFAULT_MIN_SEGMENT_SECONDS,
    fpcalc_path: Path | None = None,
    db_path: Path | None = None,
    max_candidates: int = 30000,
) -> dict[str, Any] | None:
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))

    duration, query = local_fp.raw_fingerprint(file_path, fpcalc_path=fpcalc_path)
    if duration < float(minimum_clip_seconds) or len(query) < 64:
        return None

    conn = connect(db_path)
    try:
        rows = segment_candidate_rows(conn, max_candidates=max_candidates)
    finally:
        conn.close()

    best_by_recording: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            stored = local_fp._parse_raw_fingerprint(row["raw_segment_json"])
        except Exception:
            continue
        score = partial_similarity(query, stored)
        recording_id = str(row["recording_id"])
        previous = best_by_recording.get(recording_id)
        if previous is not None and float(previous["score"]) >= score:
            continue
        best_by_recording[recording_id] = {
            "id": int(row["segment_id"]),
            "fingerprint_id": int(row["fingerprint_id"]),
            "recording_id": recording_id,
            "audio_file_id": int(row["audio_file_id"]),
            "artist": str(row["artist"]),
            "title": str(row["title"]),
            "album": str(row["album"] or ""),
            "source": str(row["source"] or "segment-v3"),
            "source_path": str(row["source_path"] or ""),
            "audio_sha256": str(row["audio_sha256"] or ""),
            "score": round(score, 2),
            "fingerprint_score": round(score, 2),
            "duration_score": 100.0,
            "duration_diff_seconds": 0.0,
            "duration_seconds": float(duration),
            "query_duration_seconds": round(float(duration), 2),
            "query_fingerprint_frames": len(query),
            "segment_start_seconds": round(float(row["start_seconds"]), 2),
            "segment_end_seconds": round(float(row["end_seconds"]), 2),
            "match_mode": "segment",
            "schema_version": SCHEMA_VERSION,
        }

    ranked = sorted(best_by_recording.values(), key=lambda item: float(item["score"]), reverse=True)
    if not ranked or float(ranked[0]["score"]) < float(threshold):
        return None
    if len(ranked) > 1:
        margin = float(ranked[0]["score"]) - float(ranked[1]["score"])
        if margin < float(minimum_margin):
            return None
        ranked[0]["runner_up_margin"] = round(margin, 2)
    else:
        ranked[0]["runner_up_margin"] = 100.0
    return ranked[0]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    counts = dict(v2_store.stats(conn))
    row = conn.execute("SELECT COUNT(*) AS count FROM fingerprint_segments").fetchone()
    counts["segments"] = int(row["count"] or 0)
    counts["schema_version"] = SCHEMA_VERSION
    return counts
