#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent Review Queue state derived from audited local identity changes.

A DetectionResult report is immutable evidence. Once a user verifies a file, the
old REJECT row must not keep appearing merely because the report still contains
it. This controller hides rows whose current recording was written by the
human-review path. Undo naturally reopens the row because the association is
removed or restored to its previous non-human source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools import review_service
from tools.review_online import OnlineReviewController


class ResolvedQueueController(OnlineReviewController):
    """Online Review controller that separates unresolved and verified items."""

    def _verified_identity(self, source_path: Path | str) -> dict[str, Any] | None:
        value = str(Path(source_path).expanduser().resolve())
        conn = review_service.connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT r.id AS recording_id,
                       r.artist,
                       r.title,
                       r.album,
                       r.status AS recording_status,
                       r.source AS recording_source,
                       af.id AS audio_file_id,
                       af.source_path
                FROM audio_files AS af
                JOIN recordings AS r ON r.id = af.recording_id
                WHERE LOWER(REPLACE(af.source_path, '/', '\\')) =
                      LOWER(REPLACE(?, '/', '\\'))
                ORDER BY af.updated_at DESC, af.id DESC
                LIMIT 1
                """,
                (value,),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            if (
                str(item.get("recording_status") or "").casefold() != "active"
                or str(item.get("recording_source") or "").casefold() != "human-review"
            ):
                return None
            return item
        finally:
            conn.close()

    def queue(
        self,
        report_path: Path | str | None = None,
        *,
        include_safe: bool = False,
    ) -> dict[str, Any]:
        result = super().queue(report_path, include_safe=include_safe)
        if str(result.get("report_kind") or "") != "real":
            result["resolved_count"] = 0
            result["resolved_items"] = []
            return result

        unresolved: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        for raw in result.get("items") or []:
            item = dict(raw)
            source = str(item.get("source_path") or "")
            verified = self._verified_identity(source) if source else None
            if verified is None:
                unresolved.append(item)
                continue
            item["resolved_identity"] = verified
            item["resolution"] = "human-verified"
            resolved.append(item)

        result["items"] = unresolved
        result["resolved_items"] = resolved
        result["resolved_count"] = len(resolved)
        return result
