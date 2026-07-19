#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Frontend-safe controller for local artist aliases and consolidation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from tools import artist_alias_service
from tools.review_queue_state import ResolvedQueueController


class ArtistAliasController(ResolvedQueueController):
    def artist_groups(self) -> list[dict[str, Any]]:
        return artist_alias_service.suggest_artist_groups(db_path=self.db_path)

    def aliases(self) -> list[dict[str, Any]]:
        return artist_alias_service.list_aliases(db_path=self.db_path)

    def preview_artist_aliases(
        self,
        canonical_artist: str,
        aliases: Iterable[str],
    ) -> dict[str, Any]:
        return artist_alias_service.preview_aliases(
            canonical_artist,
            aliases,
            db_path=self.db_path,
        )

    def apply_artist_aliases(
        self,
        canonical_artist: str,
        aliases: Iterable[str],
        *,
        reviewer: str = "local-user",
        reason: str = "artist alias consolidation",
    ) -> dict[str, Any]:
        return artist_alias_service.apply_aliases(
            canonical_artist,
            aliases,
            reviewer=reviewer,
            reason=reason,
            db_path=self.db_path,
        )

    def undo(self, action_id: str = "") -> dict[str, Any]:
        actions = self.history(limit=500, include_undone=False)
        selected = None
        if action_id:
            selected = next((item for item in actions if item["id"] == action_id), None)
        elif actions:
            selected = actions[0]
        if selected is not None and selected.get("action_type") == "canonicalize-artist":
            return artist_alias_service.undo_alias_action(
                str(selected["id"]),
                db_path=self.db_path,
            )
        return super().undo(action_id)
