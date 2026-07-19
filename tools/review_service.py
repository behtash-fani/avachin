#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audited human-review operations for Avachin's local acoustic memory.

This module is the only write surface used by the Review Center. Every mutation
creates a SQLite backup, records a compact before/after audit entry and supports
an explicit undo. Audio files are never renamed, moved, retagged or deleted.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools import fingerprint_store_v2 as store
from tools import local_fingerprint_library as local_fp
from tools import partial_fingerprint_store as partial_store

REVIEW_SCHEMA_VERSION = 1
UNKNOWN_VALUES = {
    "",
    "-",
    "unknown",
    "unknown artist",
    "untitled",
    "no title",
    "track",
    "track 1",
    "n/a",
    "na",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _identity_text(value: Any, field: str) -> str:
    text = _text(value)
    if not text or text.casefold() in UNKNOWN_VALUES:
        raise ValueError(f"{field} must contain a real value")
    return text


def database_path(db_path: Path | str | None = None) -> Path:
    return Path(db_path).expanduser().resolve() if db_path else local_fp.local_db_path().resolve()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the local DB and ensure acoustic plus review schemas exist."""
    path = database_path(db_path)
    conn = partial_store.connect(path)
    ensure_review_schema(conn)
    conn.commit()
    return conn


def ensure_review_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS review_actions (
            id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'applied',
            reviewer TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_recording_id TEXT,
            target_recording_id TEXT,
            audio_file_id INTEGER,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            undone_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_review_actions_created
            ON review_actions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_review_actions_status
            ON review_actions(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_review_actions_source
            ON review_actions(source_recording_id);
        CREATE INDEX IF NOT EXISTS idx_review_actions_target
            ON review_actions(target_recording_id);
        """
    )
    store.set_meta(conn, "review_schema_version", REVIEW_SCHEMA_VERSION)


def _backup_dir(db_path: Path) -> Path:
    path = db_path.parent / "review_backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(db_path: Path | str | None, action_id: str) -> Path:
    """Create a consistent SQLite snapshot before a review mutation."""
    source_path = database_path(db_path)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = _backup_dir(source_path) / f"{stamp}-{action_id}.sqlite3"
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    return target


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def _recording_row(conn: sqlite3.Connection, recording_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if row is None:
        raise KeyError(f"recording not found: {recording_id}")
    return row


def _audio_row(conn: sqlite3.Connection, audio_file_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM audio_files WHERE id = ?", (int(audio_file_id),)).fetchone()
    if row is None:
        raise KeyError(f"audio file not found: {audio_file_id}")
    return row


def _ids(conn: sqlite3.Connection, sql: str, params: Iterable[Any]) -> list[Any]:
    return [row[0] for row in conn.execute(sql, tuple(params)).fetchall()]


def _insert_action(
    conn: sqlite3.Connection,
    *,
    action_id: str,
    action_type: str,
    reviewer: str,
    reason: str,
    source_recording_id: str = "",
    target_recording_id: str = "",
    audio_file_id: int | None = None,
    before: dict[str, Any],
    after: dict[str, Any],
    backup_path: Path,
) -> None:
    conn.execute(
        """
        INSERT INTO review_actions (
            id, action_type, status, reviewer, reason,
            source_recording_id, target_recording_id, audio_file_id,
            before_json, after_json, backup_path, created_at
        ) VALUES (?, ?, 'applied', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            action_type,
            _text(reviewer) or "local-user",
            _text(reason) or "manual review correction",
            source_recording_id or None,
            target_recording_id or None,
            audio_file_id,
            json.dumps(before, ensure_ascii=False, sort_keys=True),
            json.dumps(after, ensure_ascii=False, sort_keys=True),
            str(backup_path),
            now_utc(),
        ),
    )


def _refresh_recording_status(conn: sqlite3.Connection, recording_id: str) -> str:
    count = int(
        conn.execute(
            "SELECT COUNT(*) FROM audio_files WHERE recording_id = ?",
            (recording_id,),
        ).fetchone()[0]
    )
    status = "active" if count else "orphaned"
    conn.execute(
        "UPDATE recordings SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_utc(), recording_id),
    )
    return status


def list_recordings(
    query: str = "",
    *,
    status: str = "",
    limit: int = 500,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        where: list[str] = []
        params: list[Any] = []
        if _text(query):
            like = f"%{_text(query)}%"
            where.append("(r.artist LIKE ? OR r.title LIKE ? OR COALESCE(r.album, '') LIKE ? OR r.id LIKE ?)")
            params.extend([like, like, like, like])
        if _text(status):
            where.append("r.status = ?")
            params.append(_text(status))
        sql = """
            SELECT r.*,
                   COUNT(DISTINCT af.id) AS audio_files,
                   COUNT(DISTINCT fp.id) AS fingerprints
            FROM recordings AS r
            LEFT JOIN audio_files AS af ON af.recording_id = r.id
            LEFT JOIN fingerprints AS fp ON fp.recording_id = r.id
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY r.id ORDER BY r.updated_at DESC, r.artist, r.title LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def recording_detail(
    recording_id: str,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        recording = _row_dict(_recording_row(conn, recording_id))
        recording["audio_files"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT af.*,
                       COUNT(DISTINCT fp.id) AS fingerprints,
                       COUNT(DISTINCT seg.id) AS segments
                FROM audio_files AS af
                LEFT JOIN fingerprints AS fp ON fp.audio_file_id = af.id
                LEFT JOIN fingerprint_segments AS seg ON seg.audio_file_id = af.id
                WHERE af.recording_id = ?
                GROUP BY af.id
                ORDER BY af.id
                """,
                (recording_id,),
            ).fetchall()
        ]
        recording["external_ids"] = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM external_ids WHERE recording_id = ? ORDER BY provider, entity_type",
                (recording_id,),
            ).fetchall()
        ]
        return recording
    finally:
        conn.close()


def reassign_audio_file(
    audio_file_id: int,
    *,
    artist: str,
    title: str,
    album: str = "",
    reviewer: str = "local-user",
    reason: str = "manual identity correction",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Move one physical audio encoding and all derived fingerprints to a new identity."""
    artist = _identity_text(artist, "artist")
    title = _identity_text(title, "title")
    album = _text(album)
    path = database_path(db_path)
    bootstrap = connect(path)
    bootstrap.close()
    action_id = uuid.uuid4().hex
    backup = create_backup(path, action_id)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        audio = _audio_row(conn, int(audio_file_id))
        source_id = str(audio["recording_id"])
        source = _recording_row(conn, source_id)
        target_id = store.stable_recording_id(artist, title, album)
        target_existing = conn.execute("SELECT * FROM recordings WHERE id = ?", (target_id,)).fetchone()
        if target_id == source_id:
            raise ValueError("the selected audio file already belongs to that recording")
        target_id = store.upsert_recording(
            conn,
            artist=artist,
            title=title,
            album=album,
            source="human-review",
            confidence=100.0,
        )
        fingerprint_ids = _ids(
            conn,
            "SELECT id FROM fingerprints WHERE audio_file_id = ? ORDER BY id",
            (int(audio_file_id),),
        )
        segment_ids = (
            _ids(
                conn,
                "SELECT id FROM fingerprint_segments WHERE audio_file_id = ? ORDER BY id",
                (int(audio_file_id),),
            )
            if _table_exists(conn, "fingerprint_segments")
            else []
        )
        before = {
            "source_recording": _row_dict(source),
            "target_recording": _row_dict(target_existing),
            "target_preexisting": target_existing is not None,
            "audio_file_id": int(audio_file_id),
            "fingerprint_ids": fingerprint_ids,
            "segment_ids": segment_ids,
        }
        stamp = now_utc()
        conn.execute(
            "UPDATE audio_files SET recording_id = ?, updated_at = ? WHERE id = ?",
            (target_id, stamp, int(audio_file_id)),
        )
        conn.execute(
            "UPDATE fingerprints SET recording_id = ?, source = 'human-review', confidence = 100.0, updated_at = ? WHERE audio_file_id = ?",
            (target_id, stamp, int(audio_file_id)),
        )
        if _table_exists(conn, "fingerprint_segments"):
            conn.execute(
                "UPDATE fingerprint_segments SET recording_id = ? WHERE audio_file_id = ?",
                (target_id, int(audio_file_id)),
            )
        source_status = _refresh_recording_status(conn, source_id)
        conn.execute(
            "UPDATE recordings SET status = 'active', updated_at = ? WHERE id = ?",
            (stamp, target_id),
        )
        after = {
            "audio_file_id": int(audio_file_id),
            "source_recording_id": source_id,
            "source_status": source_status,
            "target_recording_id": target_id,
            "target_identity": {"artist": artist, "title": title, "album": album},
        }
        _insert_action(
            conn,
            action_id=action_id,
            action_type="reassign-audio",
            reviewer=reviewer,
            reason=reason,
            source_recording_id=source_id,
            target_recording_id=target_id,
            audio_file_id=int(audio_file_id),
            before=before,
            after=after,
            backup_path=backup,
        )
        conn.commit()
        return {"action_id": action_id, "status": "applied", "backup_path": str(backup), **after}
    except Exception:
        conn.rollback()
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        conn.close()


def merge_recordings(
    source_recording_id: str,
    target_recording_id: str,
    *,
    reviewer: str = "local-user",
    reason: str = "manual duplicate merge",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Move every encoding and identifier from source into target, preserving undo."""
    source_recording_id = _text(source_recording_id)
    target_recording_id = _text(target_recording_id)
    if not source_recording_id or not target_recording_id or source_recording_id == target_recording_id:
        raise ValueError("source and target recordings must be different")
    path = database_path(db_path)
    bootstrap = connect(path)
    bootstrap.close()
    action_id = uuid.uuid4().hex
    backup = create_backup(path, action_id)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        source = _recording_row(conn, source_recording_id)
        target = _recording_row(conn, target_recording_id)
        audio_ids = _ids(conn, "SELECT id FROM audio_files WHERE recording_id = ? ORDER BY id", (source_recording_id,))
        fingerprint_ids = _ids(conn, "SELECT id FROM fingerprints WHERE recording_id = ? ORDER BY id", (source_recording_id,))
        segment_ids = (
            _ids(conn, "SELECT id FROM fingerprint_segments WHERE recording_id = ? ORDER BY id", (source_recording_id,))
            if _table_exists(conn, "fingerprint_segments")
            else []
        )
        external_id_ids = _ids(conn, "SELECT id FROM external_ids WHERE recording_id = ? ORDER BY id", (source_recording_id,))
        before = {
            "source_recording": _row_dict(source),
            "target_recording": _row_dict(target),
            "audio_ids": audio_ids,
            "fingerprint_ids": fingerprint_ids,
            "segment_ids": segment_ids,
            "external_id_ids": external_id_ids,
        }
        stamp = now_utc()
        conn.execute("UPDATE audio_files SET recording_id = ?, updated_at = ? WHERE recording_id = ?", (target_recording_id, stamp, source_recording_id))
        conn.execute("UPDATE fingerprints SET recording_id = ?, source = 'human-review', updated_at = ? WHERE recording_id = ?", (target_recording_id, stamp, source_recording_id))
        if _table_exists(conn, "fingerprint_segments"):
            conn.execute("UPDATE fingerprint_segments SET recording_id = ? WHERE recording_id = ?", (target_recording_id, source_recording_id))
        conn.execute("UPDATE external_ids SET recording_id = ? WHERE recording_id = ?", (target_recording_id, source_recording_id))
        conn.execute("UPDATE recordings SET status = 'merged', updated_at = ? WHERE id = ?", (stamp, source_recording_id))
        conn.execute("UPDATE recordings SET status = 'active', updated_at = ? WHERE id = ?", (stamp, target_recording_id))
        after = {
            "source_recording_id": source_recording_id,
            "target_recording_id": target_recording_id,
            "audio_files_moved": len(audio_ids),
            "fingerprints_moved": len(fingerprint_ids),
            "segments_moved": len(segment_ids),
            "external_ids_moved": len(external_id_ids),
        }
        _insert_action(
            conn,
            action_id=action_id,
            action_type="merge-recordings",
            reviewer=reviewer,
            reason=reason,
            source_recording_id=source_recording_id,
            target_recording_id=target_recording_id,
            before=before,
            after=after,
            backup_path=backup,
        )
        conn.commit()
        return {"action_id": action_id, "status": "applied", "backup_path": str(backup), **after}
    except Exception:
        conn.rollback()
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        conn.close()


def revoke_recording(
    recording_id: str,
    *,
    reviewer: str = "local-user",
    reason: str = "manual association revoke",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Disable a recording from full and partial matching without deleting evidence."""
    recording_id = _text(recording_id)
    path = database_path(db_path)
    bootstrap = connect(path)
    bootstrap.close()
    action_id = uuid.uuid4().hex
    backup = create_backup(path, action_id)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        recording = _recording_row(conn, recording_id)
        before = {"recording": _row_dict(recording)}
        conn.execute(
            "UPDATE recordings SET status = 'revoked', updated_at = ? WHERE id = ?",
            (now_utc(), recording_id),
        )
        after = {"recording_id": recording_id, "status": "revoked"}
        _insert_action(
            conn,
            action_id=action_id,
            action_type="revoke-recording",
            reviewer=reviewer,
            reason=reason,
            source_recording_id=recording_id,
            before=before,
            after=after,
            backup_path=backup,
        )
        conn.commit()
        return {"action_id": action_id, "backup_path": str(backup), **after}
    except Exception:
        conn.rollback()
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        conn.close()


def history(
    *,
    limit: int = 200,
    include_undone: bool = True,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        sql = "SELECT * FROM review_actions"
        params: list[Any] = []
        if not include_undone:
            sql += " WHERE status = 'applied'"
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, int(limit)))
        result: list[dict[str, Any]] = []
        for row in conn.execute(sql, tuple(params)).fetchall():
            item = dict(row)
            item["before"] = json.loads(item.pop("before_json"))
            item["after"] = json.loads(item.pop("after_json"))
            result.append(item)
        return result
    finally:
        conn.close()


def undo_action(
    action_id: str = "",
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Undo one applied review action using its compact audit snapshot."""
    path = database_path(db_path)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _text(action_id):
            row = conn.execute(
                "SELECT * FROM review_actions WHERE id = ? AND status = 'applied'",
                (_text(action_id),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM review_actions WHERE status = 'applied' ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise KeyError("no applied review action is available to undo")
        item = dict(row)
        before = json.loads(item["before_json"])
        action_type = str(item["action_type"])
        stamp = now_utc()

        if action_type == "reassign-audio":
            audio_file_id = int(before["audio_file_id"])
            source = dict(before["source_recording"])
            source_id = str(source["id"])
            target_id = str(item.get("target_recording_id") or "")
            conn.execute("UPDATE audio_files SET recording_id = ?, updated_at = ? WHERE id = ?", (source_id, stamp, audio_file_id))
            conn.execute("UPDATE fingerprints SET recording_id = ?, updated_at = ? WHERE audio_file_id = ?", (source_id, stamp, audio_file_id))
            if _table_exists(conn, "fingerprint_segments"):
                conn.execute("UPDATE fingerprint_segments SET recording_id = ? WHERE audio_file_id = ?", (source_id, audio_file_id))
            conn.execute("UPDATE recordings SET status = ?, updated_at = ? WHERE id = ?", (str(source.get("status") or "active"), stamp, source_id))
            if target_id:
                _refresh_recording_status(conn, target_id)

        elif action_type == "merge-recordings":
            source = dict(before["source_recording"])
            target = dict(before["target_recording"])
            source_id = str(source["id"])
            target_id = str(target["id"])
            for table, ids in (
                ("audio_files", before.get("audio_ids") or []),
                ("fingerprints", before.get("fingerprint_ids") or []),
                ("fingerprint_segments", before.get("segment_ids") or []),
                ("external_ids", before.get("external_id_ids") or []),
            ):
                if not ids or not _table_exists(conn, table):
                    continue
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE {table} SET recording_id = ? WHERE id IN ({placeholders})",
                    (source_id, *ids),
                )
            conn.execute("UPDATE recordings SET status = ?, updated_at = ? WHERE id = ?", (str(source.get("status") or "active"), stamp, source_id))
            conn.execute("UPDATE recordings SET status = ?, updated_at = ? WHERE id = ?", (str(target.get("status") or "active"), stamp, target_id))

        elif action_type == "revoke-recording":
            recording = dict(before["recording"])
            conn.execute(
                "UPDATE recordings SET status = ?, updated_at = ? WHERE id = ?",
                (str(recording.get("status") or "active"), stamp, str(recording["id"])),
            )
        else:
            raise RuntimeError(f"unsupported review action type: {action_type}")

        conn.execute(
            "UPDATE review_actions SET status = 'undone', undone_at = ? WHERE id = ?",
            (stamp, str(item["id"])),
        )
        conn.commit()
        return {"action_id": str(item["id"]), "action_type": action_type, "status": "undone", "undone_at": stamp}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def latest_detection_report(report_root: Path | str | None = None) -> Path | None:
    root = Path(report_root).expanduser().resolve() if report_root else (Path(__file__).resolve().parents[1] / "reports")
    if not root.exists():
        return None
    candidates = list(root.rglob("detection-report.json")) + list(root.rglob("detection_report.json"))
    candidates = [item for item in candidates if item.is_file()]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def load_review_queue(
    report_path: Path | str | None = None,
    *,
    report_root: Path | str | None = None,
    include_safe: bool = False,
) -> dict[str, Any]:
    path = Path(report_path).expanduser().resolve() if report_path else latest_detection_report(report_root)
    if path is None or not path.is_file():
        return {"report_path": "", "summary": {}, "items": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    detections = payload.get("detections") if isinstance(payload, dict) else []
    if not isinstance(detections, list):
        detections = []
    items: list[dict[str, Any]] = []
    for raw in detections:
        if not isinstance(raw, dict):
            continue
        decision = _text(raw.get("decision")).upper()
        safe = bool(raw.get("safe_to_apply"))
        if not include_safe and decision not in {"REVIEW", "REJECT"} and safe:
            continue
        confidence = raw.get("confidence") if isinstance(raw.get("confidence"), dict) else {}
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        items.append(
            {
                "source_path": _text(raw.get("source_path")),
                "decision": decision,
                "reason": _text(raw.get("decision_reason")),
                "safe_to_apply": safe,
                "artist": _text(raw.get("artist")),
                "title": _text(raw.get("title")),
                "album": _text(raw.get("album")),
                "overall_confidence": confidence.get("overall"),
                "audio_confidence": confidence.get("audio"),
                "identity_confidence": confidence.get("identity"),
                "provider": _text(evidence.get("provider")),
                "match_mode": _text(evidence.get("match_mode")),
                "fingerprint_score": evidence.get("fingerprint_score"),
            }
        )
    return {"report_path": str(path), "summary": payload.get("summary") or {}, "items": items}


def find_audio_by_path(
    source_path: Path | str,
    *,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    value = str(Path(source_path).expanduser().resolve())
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT af.*, r.artist, r.title, r.album, r.status AS recording_status
            FROM audio_files AS af
            JOIN recordings AS r ON r.id = af.recording_id
            WHERE LOWER(REPLACE(af.source_path, '/', '\\')) = LOWER(REPLACE(?, '/', '\\'))
            ORDER BY af.id
            """,
            (value,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def copy_database_snapshot(
    destination: Path | str,
    *,
    db_path: Path | str | None = None,
) -> Path:
    """Explicit helper for support/export flows; it never replaces the live DB."""
    source = database_path(db_path)
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
