#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frontend-safe controller for Avachin Review Center.

The GUI and CLI use this facade rather than writing SQLite directly. It extends
the audited review service with safe segment disabling for revoked recordings
and human-approved learning for previously rejected files.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from tools import fingerprint_store_v2 as store
from tools import local_fingerprint_library as local_fp
from tools import partial_fingerprint_store as partial_store
from tools import review_service


class ReviewController:
    def __init__(self, *, db_path: Path | str | None = None) -> None:
        self.db_path = review_service.database_path(db_path)

    def queue(self, report_path: Path | str | None = None, *, include_safe: bool = False) -> dict[str, Any]:
        return review_service.load_review_queue(report_path, include_safe=include_safe)

    def search(self, query: str = "", *, status: str = "", limit: int = 500) -> list[dict[str, Any]]:
        return review_service.list_recordings(query, status=status, limit=limit, db_path=self.db_path)

    def detail(self, recording_id: str) -> dict[str, Any]:
        return review_service.recording_detail(recording_id, db_path=self.db_path)

    def find_path(self, source_path: Path | str) -> list[dict[str, Any]]:
        return review_service.find_audio_by_path(source_path, db_path=self.db_path)

    def reassign(
        self,
        audio_file_id: int,
        *,
        artist: str,
        title: str,
        album: str = "",
        reviewer: str = "local-user",
        reason: str = "manual identity correction",
    ) -> dict[str, Any]:
        return review_service.reassign_audio_file(
            audio_file_id,
            artist=artist,
            title=title,
            album=album,
            reviewer=reviewer,
            reason=reason,
            db_path=self.db_path,
        )

    def merge(
        self,
        source_recording_id: str,
        target_recording_id: str,
        *,
        reviewer: str = "local-user",
        reason: str = "manual duplicate merge",
    ) -> dict[str, Any]:
        return review_service.merge_recordings(
            source_recording_id,
            target_recording_id,
            reviewer=reviewer,
            reason=reason,
            db_path=self.db_path,
        )

    def revoke(
        self,
        recording_id: str,
        *,
        reviewer: str = "local-user",
        reason: str = "manual association revoke",
    ) -> dict[str, Any]:
        """Revoke full matching and neutralize derived segment candidates."""
        result = review_service.revoke_recording(
            recording_id,
            reviewer=reviewer,
            reason=reason,
            db_path=self.db_path,
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            partial_store.ensure_segment_schema(conn)
            with conn:
                cursor = conn.execute(
                    """
                    UPDATE fingerprint_segments
                    SET raw_segment_json = '[]',
                        frame_count = 0,
                        segment_sha256 = ?
                    WHERE recording_id = ?
                    """,
                    (f"revoked:{result['action_id']}", recording_id),
                )
            result["segments_disabled"] = max(0, int(cursor.rowcount or 0))
        finally:
            conn.close()
        return result

    def learn_rejected_file(
        self,
        source_path: Path | str,
        *,
        artist: str,
        title: str,
        album: str = "",
        reviewer: str = "local-user",
        reason: str = "human-approved rejected-file identity",
    ) -> dict[str, Any]:
        """Learn one manually verified file with audit, backup and segment indexing."""
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        artist = review_service._identity_text(artist, "artist")
        title = review_service._identity_text(title, "title")
        album = review_service._text(album)
        duration, fingerprint = local_fp.raw_fingerprint(path)
        audio_sha = local_fp.audio_sha256(path)
        fp_sha = local_fp.fingerprint_sha256(fingerprint)
        raw_json = json.dumps(fingerprint, separators=(",", ":"))

        bootstrap = review_service.connect(self.db_path)
        try:
            existing_audio = bootstrap.execute(
                "SELECT id, recording_id FROM audio_files WHERE audio_sha256 = ?",
                (audio_sha,),
            ).fetchone()
        finally:
            bootstrap.close()
        if existing_audio is not None:
            return self.reassign(
                int(existing_audio["id"]),
                artist=artist,
                title=title,
                album=album,
                reviewer=reviewer,
                reason=reason,
            )

        action_id = uuid.uuid4().hex
        backup = review_service.create_backup(self.db_path, action_id)
        conn = review_service.connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            target_id = store.stable_recording_id(artist, title, album)
            target_before = conn.execute("SELECT * FROM recordings WHERE id = ?", (target_id,)).fetchone()
            target_id = store.upsert_recording(
                conn,
                artist=artist,
                title=title,
                album=album,
                source="human-review",
                confidence=100.0,
            )
            audio_file_id = store.upsert_audio_file(
                conn,
                recording_id=target_id,
                audio_sha256=audio_sha,
                source_path=str(path),
                duration_seconds=duration,
            )
            fingerprint_id = store.replace_fingerprint(
                conn,
                recording_id=target_id,
                audio_file_id=audio_file_id,
                fingerprint_sha256=fp_sha,
                fingerprint_frames=len(fingerprint),
                raw_fingerprint_json=raw_json,
                duration_seconds=duration,
                source="human-review",
                confidence=100.0,
            )
            partial_store.ensure_segment_schema(conn)
            segments = partial_store.replace_segments_for_fingerprint(conn, fingerprint_id)
            before = {
                "target_recording": dict(target_before) if target_before is not None else {},
                "target_preexisting": target_before is not None,
                "source_path": str(path),
            }
            after = {
                "recording_id": target_id,
                "audio_file_id": audio_file_id,
                "fingerprint_id": fingerprint_id,
                "segments": segments,
                "artist": artist,
                "title": title,
                "album": album,
            }
            review_service._insert_action(
                conn,
                action_id=action_id,
                action_type="manual-learn",
                reviewer=reviewer,
                reason=reason,
                target_recording_id=target_id,
                audio_file_id=audio_file_id,
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

    def history(self, *, limit: int = 200, include_undone: bool = True) -> list[dict[str, Any]]:
        return review_service.history(
            limit=limit,
            include_undone=include_undone,
            db_path=self.db_path,
        )

    def undo(self, action_id: str = "") -> dict[str, Any]:
        actions = self.history(limit=500, include_undone=False)
        selected = None
        if action_id:
            selected = next((item for item in actions if item["id"] == action_id), None)
        elif actions:
            selected = actions[0]
        if selected is None:
            raise KeyError("no applied review action is available to undo")

        if selected["action_type"] == "manual-learn":
            conn = review_service.connect(self.db_path)
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT * FROM review_actions WHERE id = ? AND status = 'applied'",
                    (selected["id"],),
                ).fetchone()
                if row is None:
                    raise KeyError(f"applied action not found: {selected['id']}")
                before = json.loads(row["before_json"])
                after = json.loads(row["after_json"])
                audio_file_id = int(after["audio_file_id"])
                recording_id = str(after["recording_id"])
                conn.execute("DELETE FROM audio_files WHERE id = ?", (audio_file_id,))
                if before.get("target_preexisting"):
                    old = dict(before.get("target_recording") or {})
                    conn.execute(
                        "UPDATE recordings SET status = ?, source = ?, confidence = ?, updated_at = ? WHERE id = ?",
                        (
                            str(old.get("status") or "active"),
                            str(old.get("source") or "manual"),
                            float(old.get("confidence") or 100.0),
                            review_service.now_utc(),
                            recording_id,
                        ),
                    )
                else:
                    review_service._refresh_recording_status(conn, recording_id)
                stamp = review_service.now_utc()
                conn.execute(
                    "UPDATE review_actions SET status = 'undone', undone_at = ? WHERE id = ?",
                    (stamp, selected["id"]),
                )
                conn.commit()
                return {
                    "action_id": selected["id"],
                    "action_type": "manual-learn",
                    "status": "undone",
                    "undone_at": stamp,
                }
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        result = review_service.undo_action(selected["id"], db_path=self.db_path)
        if selected["action_type"] == "revoke-recording":
            recording_id = str(selected.get("source_recording_id") or "")
            conn = partial_store.connect(self.db_path)
            try:
                fingerprint_ids = [
                    int(row[0])
                    for row in conn.execute(
                        "SELECT id FROM fingerprints WHERE recording_id = ? ORDER BY id",
                        (recording_id,),
                    ).fetchall()
                ]
                with conn:
                    rebuilt = 0
                    for fingerprint_id in fingerprint_ids:
                        rebuilt += partial_store.replace_segments_for_fingerprint(conn, fingerprint_id)
                result["segments_rebuilt"] = rebuilt
            finally:
                conn.close()
        return result
