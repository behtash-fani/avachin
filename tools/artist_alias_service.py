#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview, apply and undo artist-name consolidation without online providers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from tools import fingerprint_store_v2 as store
from tools import review_service
from tools.artist_alias_core import (
    artist_alias_key,
    clean_artist,
    ensure_alias_schema,
    register_alias,
)


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_artist(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            output.append(text)
    return output


def _artist_folder(source_path: Any) -> str:
    value = clean_artist(source_path)
    if not value:
        return ""
    path = Path(value)
    parts = list(path.parts)
    # In the current library convention the artist is commonly three levels
    # above the file: Artist / Album-or-Singles / Track.mp3.
    if len(parts) >= 3:
        return str(Path(*parts[:-2]))
    return str(path.parent)


def _recordings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT r.*,
                   COUNT(DISTINCT af.id) AS audio_files,
                   COUNT(DISTINCT fp.id) AS fingerprints
            FROM recordings AS r
            LEFT JOIN audio_files AS af ON af.recording_id = r.id
            LEFT JOIN fingerprints AS fp ON fp.recording_id = r.id
            GROUP BY r.id
            ORDER BY r.artist, r.title, r.album
            """
        ).fetchall()
    ]


def suggest_artist_groups(*, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Suggest spacing/punctuation variants already present in local memory."""
    conn = review_service.connect(db_path)
    try:
        ensure_alias_schema(conn)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in _recordings(conn):
            if str(row.get("status") or "").casefold() not in {"active", "orphaned"}:
                continue
            key = artist_alias_key(row.get("artist"))
            if key:
                grouped[key].append(row)
        output: list[dict[str, Any]] = []
        for key, rows in grouped.items():
            variants = _unique(row.get("artist") for row in rows)
            if len(variants) < 2:
                continue
            counts: dict[str, int] = defaultdict(int)
            for row in rows:
                counts[clean_artist(row.get("artist"))] += int(row.get("audio_files") or 0)
            preferred = sorted(
                variants,
                key=lambda value: (
                    -counts[value],
                    -int(" " in value),
                    -len(value),
                    value.casefold(),
                ),
            )[0]
            output.append(
                {
                    "group_key": key,
                    "suggested_canonical": preferred,
                    "variants": variants,
                    "recordings": len(rows),
                    "audio_files": sum(int(row.get("audio_files") or 0) for row in rows),
                }
            )
        return sorted(output, key=lambda item: (-int(item["audio_files"]), item["group_key"]))
    finally:
        conn.close()


def list_aliases(*, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    conn = review_service.connect(db_path)
    try:
        ensure_alias_schema(conn)
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM artist_aliases ORDER BY canonical_artist, alias_text"
            ).fetchall()
        ]
    finally:
        conn.close()


def preview_aliases(
    canonical_artist: str,
    aliases: Iterable[str],
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    canonical = clean_artist(canonical_artist)
    variants = _unique([canonical, *aliases])
    if not canonical or len(variants) < 2:
        raise ValueError("enter one canonical artist and at least one different alias")
    keys = {artist_alias_key(value) for value in variants}
    conn = review_service.connect(db_path)
    try:
        ensure_alias_schema(conn)
        conflicts: list[dict[str, str]] = []
        for key in keys:
            row = conn.execute(
                "SELECT alias_text, canonical_artist FROM artist_aliases WHERE alias_key = ? AND status = 'active'",
                (key,),
            ).fetchone()
            if row is not None and clean_artist(row["canonical_artist"]).casefold() != canonical.casefold():
                conflicts.append(dict(row))

        affected: list[dict[str, Any]] = []
        folders: set[str] = set()
        for row in _recordings(conn):
            if artist_alias_key(row.get("artist")) not in keys:
                continue
            audio_rows = [
                dict(item)
                for item in conn.execute(
                    "SELECT id, source_path FROM audio_files WHERE recording_id = ? ORDER BY id",
                    (row["id"],),
                ).fetchall()
            ]
            for audio in audio_rows:
                folder = _artist_folder(audio.get("source_path"))
                if folder:
                    folders.add(folder)
            target_id = store.stable_recording_id(
                canonical,
                clean_artist(row.get("title")),
                clean_artist(row.get("album")),
            )
            affected.append(
                {
                    "source_recording_id": row["id"],
                    "source_artist": row["artist"],
                    "title": row["title"],
                    "album": row.get("album") or "",
                    "target_recording_id": target_id,
                    "audio_files": len(audio_rows),
                    "already_canonical": row["id"] == target_id,
                }
            )
        return {
            "status": "preview",
            "canonical_artist": canonical,
            "aliases": variants,
            "recordings_affected": len(affected),
            "audio_files_affected": sum(int(item["audio_files"]) for item in affected),
            "source_folders": sorted(folders, key=str.casefold),
            "planned_recordings": affected,
            "conflicts": conflicts,
            "network_requests": 0,
            "music_files_changed": False,
        }
    finally:
        conn.close()


def _ids(conn: sqlite3.Connection, table: str, recording_id: str) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM {table} WHERE recording_id = ? ORDER BY id",
            (recording_id,),
        ).fetchall()
    ]


def apply_aliases(
    canonical_artist: str,
    aliases: Iterable[str],
    *,
    reviewer: str = "local-user",
    reason: str = "artist alias consolidation",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    preview = preview_aliases(canonical_artist, aliases, db_path=db_path)
    if preview["conflicts"]:
        raise ValueError("one or more aliases already point to a different canonical artist")
    canonical = str(preview["canonical_artist"])
    variants = list(preview["aliases"])
    keys = {artist_alias_key(value) for value in variants}
    path = review_service.database_path(db_path)
    bootstrap = review_service.connect(path)
    bootstrap.close()
    action_id = uuid.uuid4().hex
    backup = review_service.create_backup(path, action_id)
    conn = review_service.connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_alias_schema(conn)
        alias_before = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM artist_aliases WHERE alias_key IN ({','.join('?' for _ in keys)})",
                tuple(keys),
            ).fetchall()
        ]
        candidate_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM recordings ORDER BY id"
            ).fetchall()
            if artist_alias_key(row["artist"]) in keys
            and str(row["status"]).casefold() in {"active", "orphaned"}
        ]
        before_recordings: dict[str, dict[str, Any]] = {
            str(row["id"]): dict(row) for row in candidate_rows
        }
        child_map: dict[str, dict[str, str]] = {
            "audio_files": {},
            "fingerprints": {},
            "fingerprint_segments": {},
        }
        target_existing: dict[str, bool] = {}
        targets: set[str] = set()
        moved_audio = moved_fingerprints = moved_segments = 0
        merged_sources: list[str] = []

        for alias in variants:
            register_alias(conn, alias, canonical)
        register_alias(conn, canonical, canonical)

        for source in candidate_rows:
            source_id = str(source["id"])
            target_id = store.stable_recording_id(
                canonical,
                clean_artist(source["title"]),
                clean_artist(source.get("album")),
            )
            if target_id == source_id:
                conn.execute(
                    "UPDATE recordings SET artist = ?, source = 'human-review', updated_at = ? WHERE id = ?",
                    (canonical, review_service.now_utc(), source_id),
                )
                continue
            existing = conn.execute("SELECT * FROM recordings WHERE id = ?", (target_id,)).fetchone()
            target_existing[target_id] = existing is not None
            if existing is not None:
                before_recordings.setdefault(target_id, dict(existing))
            actual_target = store.upsert_recording(
                conn,
                artist=canonical,
                title=clean_artist(source["title"]),
                album=clean_artist(source.get("album")),
                source="human-review",
                confidence=100.0,
            )
            targets.add(actual_target)
            stamp = review_service.now_utc()
            for table in ("audio_files", "fingerprints", "fingerprint_segments"):
                if not review_service._table_exists(conn, table):
                    continue
                ids = _ids(conn, table, source_id)
                for row_id in ids:
                    child_map[table][str(row_id)] = source_id
                if not ids:
                    continue
                conn.execute(
                    f"UPDATE {table} SET recording_id = ? WHERE id IN ({','.join('?' for _ in ids)})",
                    (actual_target, *ids),
                )
                if table == "audio_files":
                    moved_audio += len(ids)
                elif table == "fingerprints":
                    moved_fingerprints += len(ids)
                else:
                    moved_segments += len(ids)
            conn.execute(
                "UPDATE recordings SET status = 'merged', updated_at = ? WHERE id = ?",
                (stamp, source_id),
            )
            conn.execute(
                "UPDATE recordings SET status = 'active', artist = ?, source = 'human-review', updated_at = ? WHERE id = ?",
                (canonical, stamp, actual_target),
            )
            merged_sources.append(source_id)

        before = {
            "canonical_artist": canonical,
            "aliases": variants,
            "alias_rows": alias_before,
            "alias_keys": sorted(keys),
            "recordings": before_recordings,
            "child_map": child_map,
            "target_existing": target_existing,
            "target_ids": sorted(targets),
        }
        after = {
            "canonical_artist": canonical,
            "aliases_registered": len(variants),
            "recordings_merged": len(merged_sources),
            "source_recording_ids": merged_sources,
            "target_recording_ids": sorted(targets),
            "audio_files_moved": moved_audio,
            "fingerprints_moved": moved_fingerprints,
            "segments_moved": moved_segments,
            "source_folders": preview["source_folders"],
            "network_requests": 0,
            "music_files_changed": False,
        }
        review_service._insert_action(
            conn,
            action_id=action_id,
            action_type="canonicalize-artist",
            reviewer=reviewer,
            reason=reason,
            before=before,
            after=after,
            backup_path=backup,
        )
        conn.commit()
        return {
            "action_id": action_id,
            "status": "applied",
            "backup_path": str(backup),
            **after,
        }
    except Exception:
        conn.rollback()
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        conn.close()


def undo_alias_action(
    action_id: str,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    conn = review_service.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM review_actions WHERE id = ? AND status = 'applied' AND action_type = 'canonicalize-artist'",
            (clean_artist(action_id),),
        ).fetchone()
        if row is None:
            raise KeyError("applied canonicalize-artist action not found")
        before = json.loads(row["before_json"])
        stamp = review_service.now_utc()

        for table, mapping in dict(before.get("child_map") or {}).items():
            if not review_service._table_exists(conn, table):
                continue
            grouped: dict[str, list[int]] = defaultdict(list)
            for row_id, recording_id in dict(mapping or {}).items():
                grouped[str(recording_id)].append(int(row_id))
            for recording_id, ids in grouped.items():
                conn.execute(
                    f"UPDATE {table} SET recording_id = ? WHERE id IN ({','.join('?' for _ in ids)})",
                    (recording_id, *ids),
                )

        recordings = dict(before.get("recordings") or {})
        for recording_id, old in recordings.items():
            conn.execute(
                """
                UPDATE recordings
                SET identity_key = ?, artist = ?, title = ?, album = ?, status = ?,
                    source = ?, confidence = ?, created_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    old["identity_key"],
                    old["artist"],
                    old["title"],
                    old.get("album"),
                    old["status"],
                    old["source"],
                    old["confidence"],
                    old["created_at"],
                    old["updated_at"],
                    recording_id,
                ),
            )

        for target_id, existed in dict(before.get("target_existing") or {}).items():
            if existed:
                continue
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM audio_files WHERE recording_id = ?",
                    (target_id,),
                ).fetchone()[0]
            )
            if count == 0:
                conn.execute("DELETE FROM recordings WHERE id = ?", (target_id,))

        alias_keys = list(before.get("alias_keys") or [])
        if alias_keys:
            conn.execute(
                f"DELETE FROM artist_aliases WHERE alias_key IN ({','.join('?' for _ in alias_keys)})",
                tuple(alias_keys),
            )
        for old in before.get("alias_rows") or []:
            conn.execute(
                """
                INSERT OR REPLACE INTO artist_aliases (
                    alias_key, alias_text, canonical_artist, canonical_key,
                    status, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    old["alias_key"], old["alias_text"], old["canonical_artist"],
                    old["canonical_key"], old["status"], old["source"],
                    old["created_at"], old["updated_at"],
                ),
            )
        conn.execute(
            "UPDATE review_actions SET status = 'undone', undone_at = ? WHERE id = ?",
            (stamp, row["id"]),
        )
        conn.commit()
        return {
            "action_id": str(row["id"]),
            "action_type": "canonicalize-artist",
            "status": "undone",
            "undone_at": stamp,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
