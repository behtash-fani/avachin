#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned SQLite storage for Avachin's local acoustic memory.

Schema V2 separates the musical recording from physical audio encodings and
from fingerprint algorithms.  The legacy ``local_fingerprints`` table is kept
untouched and migrated non-destructively, one row at a time.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 2
SCHEMA_VERSION_KEY = "schema_version"
LEGACY_TABLE = "local_fingerprints"
LEGACY_IMPORT_NAME = "local_fingerprints_v1"
DEFAULT_ALGORITHM = "chromaprint_raw"
DEFAULT_ALGORITHM_VERSION = "1"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_identity_part(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def recording_identity_key(artist: str, title: str, album: str = "") -> str:
    payload = "\x1f".join(
        (
            normalize_identity_part(artist),
            normalize_identity_part(title),
            normalize_identity_part(album),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_recording_id(artist: str, title: str, album: str = "") -> str:
    return "rec_" + recording_identity_key(artist, title, album)[:32]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row[0])


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, str(value), now_utc()),
    )


def ensure_schema(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recordings (
            id TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL UNIQUE,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            album TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL DEFAULT 'manual',
            confidence REAL NOT NULL DEFAULT 100.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audio_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            audio_sha256 TEXT UNIQUE,
            source_path TEXT,
            duration_seconds REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            audio_file_id INTEGER NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
            algorithm TEXT NOT NULL,
            algorithm_version TEXT NOT NULL,
            fingerprint_sha256 TEXT NOT NULL,
            fingerprint_frames INTEGER NOT NULL,
            duration_seconds REAL,
            raw_fingerprint_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            confidence REAL NOT NULL DEFAULT 100.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(audio_file_id, algorithm, algorithm_version)
        );

        CREATE TABLE IF NOT EXISTS external_ids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            entity_type TEXT NOT NULL DEFAULT 'recording',
            external_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(provider, entity_type, external_id)
        );

        CREATE TABLE IF NOT EXISTS legacy_imports (
            legacy_table TEXT NOT NULL,
            legacy_id INTEGER NOT NULL,
            fingerprint_id INTEGER NOT NULL REFERENCES fingerprints(id) ON DELETE CASCADE,
            imported_at TEXT NOT NULL,
            PRIMARY KEY(legacy_table, legacy_id)
        );

        CREATE INDEX IF NOT EXISTS idx_recordings_artist_title
            ON recordings(artist, title);
        CREATE INDEX IF NOT EXISTS idx_audio_files_recording
            ON audio_files(recording_id);
        CREATE INDEX IF NOT EXISTS idx_audio_files_duration
            ON audio_files(duration_seconds);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_recording
            ON fingerprints(recording_id);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_duration
            ON fingerprints(duration_seconds);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_hash
            ON fingerprints(fingerprint_sha256);
        CREATE INDEX IF NOT EXISTS idx_external_ids_recording
            ON external_ids(recording_id);
        """
    )
    set_meta(conn, SCHEMA_VERSION_KEY, SCHEMA_VERSION)
    migrated = migrate_legacy_rows(conn)
    conn.commit()
    return {"schema_version": SCHEMA_VERSION, "legacy_rows_migrated": migrated}


def upsert_recording(
    conn: sqlite3.Connection,
    *,
    artist: str,
    title: str,
    album: str = "",
    source: str = "manual",
    confidence: float = 100.0,
    timestamp: str | None = None,
) -> str:
    timestamp = timestamp or now_utc()
    identity_key = recording_identity_key(artist, title, album)
    recording_id = stable_recording_id(artist, title, album)
    conn.execute(
        """
        INSERT INTO recordings (
            id, identity_key, artist, title, album, status, source,
            confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        ON CONFLICT(identity_key) DO UPDATE SET
            artist = excluded.artist,
            title = excluded.title,
            album = excluded.album,
            status = 'active',
            source = excluded.source,
            confidence = MAX(recordings.confidence, excluded.confidence),
            updated_at = excluded.updated_at
        """,
        (
            recording_id,
            identity_key,
            artist,
            title,
            album or None,
            source or "manual",
            float(confidence),
            timestamp,
            timestamp,
        ),
    )
    row = conn.execute(
        "SELECT id FROM recordings WHERE identity_key = ?",
        (identity_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError("recording upsert failed")
    return str(row[0])


def upsert_audio_file(
    conn: sqlite3.Connection,
    *,
    recording_id: str,
    audio_sha256: str | None,
    source_path: str = "",
    duration_seconds: float | None = None,
    timestamp: str | None = None,
) -> int:
    timestamp = timestamp or now_utc()
    audio_hash = str(audio_sha256 or "").strip() or None
    if audio_hash:
        row = conn.execute(
            "SELECT id FROM audio_files WHERE audio_sha256 = ?",
            (audio_hash,),
        ).fetchone()
        if row is not None:
            audio_file_id = int(row[0])
            conn.execute(
                """
                UPDATE audio_files
                SET recording_id = ?, source_path = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    recording_id,
                    source_path or None,
                    duration_seconds,
                    timestamp,
                    audio_file_id,
                ),
            )
            return audio_file_id

    cursor = conn.execute(
        """
        INSERT INTO audio_files (
            recording_id, audio_sha256, source_path, duration_seconds,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            recording_id,
            audio_hash,
            source_path or None,
            duration_seconds,
            timestamp,
            timestamp,
        ),
    )
    return int(cursor.lastrowid)


def replace_fingerprint(
    conn: sqlite3.Connection,
    *,
    recording_id: str,
    audio_file_id: int,
    fingerprint_sha256: str,
    fingerprint_frames: int,
    raw_fingerprint_json: str,
    duration_seconds: float | None,
    source: str = "manual",
    confidence: float = 100.0,
    algorithm: str = DEFAULT_ALGORITHM,
    algorithm_version: str = DEFAULT_ALGORITHM_VERSION,
    timestamp: str | None = None,
) -> int:
    timestamp = timestamp or now_utc()
    conn.execute(
        """
        INSERT INTO fingerprints (
            recording_id, audio_file_id, algorithm, algorithm_version,
            fingerprint_sha256, fingerprint_frames, duration_seconds,
            raw_fingerprint_json, source, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(audio_file_id, algorithm, algorithm_version) DO UPDATE SET
            recording_id = excluded.recording_id,
            fingerprint_sha256 = excluded.fingerprint_sha256,
            fingerprint_frames = excluded.fingerprint_frames,
            duration_seconds = excluded.duration_seconds,
            raw_fingerprint_json = excluded.raw_fingerprint_json,
            source = excluded.source,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at
        """,
        (
            recording_id,
            int(audio_file_id),
            algorithm,
            algorithm_version,
            fingerprint_sha256,
            int(fingerprint_frames),
            duration_seconds,
            raw_fingerprint_json,
            source or "manual",
            float(confidence),
            timestamp,
            timestamp,
        ),
    )
    row = conn.execute(
        """
        SELECT id FROM fingerprints
        WHERE audio_file_id = ? AND algorithm = ? AND algorithm_version = ?
        """,
        (int(audio_file_id), algorithm, algorithm_version),
    ).fetchone()
    if row is None:
        raise RuntimeError("fingerprint upsert failed")
    return int(row[0])


def migrate_legacy_rows(conn: sqlite3.Connection) -> int:
    if not table_exists(conn, LEGACY_TABLE):
        return 0

    rows = conn.execute(
        """
        SELECT legacy.*
        FROM local_fingerprints AS legacy
        LEFT JOIN legacy_imports AS imported
          ON imported.legacy_table = ? AND imported.legacy_id = legacy.id
        WHERE imported.legacy_id IS NULL
        ORDER BY legacy.id ASC
        """,
        (LEGACY_IMPORT_NAME,),
    ).fetchall()

    migrated = 0
    for row in rows:
        legacy_id = int(row["id"])
        artist = str(row["artist"] or "").strip()
        title = str(row["title"] or "").strip()
        if not artist or not title:
            continue
        album = str(row["album"] or "").strip()
        timestamp = str(row["updated_at"] or row["created_at"] or now_utc())
        source = str(row["source"] or "legacy-v1")
        confidence = float(row["confidence"] or 100.0)
        recording_id = upsert_recording(
            conn,
            artist=artist,
            title=title,
            album=album,
            source=source,
            confidence=confidence,
            timestamp=timestamp,
        )
        audio_file_id = upsert_audio_file(
            conn,
            recording_id=recording_id,
            audio_sha256=row["audio_sha256"],
            source_path=str(row["source_path"] or ""),
            duration_seconds=row["duration_seconds"],
            timestamp=timestamp,
        )
        fingerprint_id = replace_fingerprint(
            conn,
            recording_id=recording_id,
            audio_file_id=audio_file_id,
            fingerprint_sha256=str(row["fingerprint_sha256"]),
            fingerprint_frames=int(row["fingerprint_frames"]),
            raw_fingerprint_json=str(row["raw_fingerprint_json"]),
            duration_seconds=row["duration_seconds"],
            source=source,
            confidence=confidence,
            timestamp=timestamp,
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO legacy_imports (
                legacy_table, legacy_id, fingerprint_id, imported_at
            ) VALUES (?, ?, ?, ?)
            """,
            (LEGACY_IMPORT_NAME, legacy_id, fingerprint_id, now_utc()),
        )
        migrated += 1

    if rows:
        set_meta(conn, "legacy_v1_last_migration_at", now_utc())
    return migrated


def candidate_rows(
    conn: sqlite3.Connection,
    *,
    duration_seconds: float,
    tolerance_seconds: float,
    max_candidates: int,
    algorithm: str = DEFAULT_ALGORITHM,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            fp.id AS id,
            fp.recording_id AS recording_id,
            fp.audio_file_id AS audio_file_id,
            fp.algorithm AS algorithm,
            fp.algorithm_version AS algorithm_version,
            fp.fingerprint_sha256 AS fingerprint_sha256,
            fp.fingerprint_frames AS fingerprint_frames,
            fp.duration_seconds AS duration_seconds,
            fp.raw_fingerprint_json AS raw_fingerprint_json,
            fp.source AS source,
            fp.confidence AS stored_confidence,
            rec.artist AS artist,
            rec.title AS title,
            rec.album AS album,
            af.audio_sha256 AS audio_sha256,
            af.source_path AS source_path
        FROM fingerprints AS fp
        JOIN recordings AS rec ON rec.id = fp.recording_id
        JOIN audio_files AS af ON af.id = fp.audio_file_id
        WHERE rec.status = 'active'
          AND fp.algorithm = ?
          AND fp.duration_seconds BETWEEN ? AND ?
        ORDER BY ABS(fp.duration_seconds - ?) ASC
        LIMIT ?
        """,
        (
            algorithm,
            duration_seconds - float(tolerance_seconds),
            duration_seconds + float(tolerance_seconds),
            duration_seconds,
            int(max_candidates),
        ),
    ).fetchall()


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    artists = int(
        conn.execute("SELECT COUNT(DISTINCT artist) FROM recordings WHERE status = 'active'").fetchone()[0]
    )
    return {
        "schema_version": int(get_meta(conn, SCHEMA_VERSION_KEY, str(SCHEMA_VERSION))),
        "recordings": count("recordings"),
        "audio_files": count("audio_files"),
        "fingerprints": count("fingerprints"),
        "external_ids": count("external_ids"),
        "artists": artists,
        "legacy_rows_imported": count("legacy_imports"),
    }


def add_external_ids(
    conn: sqlite3.Connection,
    recording_id: str,
    identifiers: Iterable[tuple[str, str, str]],
) -> int:
    added = 0
    for provider, entity_type, external_id in identifiers:
        provider = str(provider or "").strip().lower()
        entity_type = str(entity_type or "recording").strip().lower() or "recording"
        external_id = str(external_id or "").strip()
        if not provider or not external_id:
            continue
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO external_ids (
                recording_id, provider, entity_type, external_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (recording_id, provider, entity_type, external_id, now_utc()),
        )
        if cursor.rowcount:
            added += 1
    return added
