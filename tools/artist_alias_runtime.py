#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install artist-alias canonicalization into local learning runtimes."""

from __future__ import annotations

from typing import Any

from tools import fingerprint_store_v2 as store
from tools.artist_alias_core import resolve_artist

_INSTALLED = False
_ORIGINAL_UPSERT = store.upsert_recording


def install_artist_alias_hook() -> None:
    """Make every future recording upsert honor the local alias table."""
    global _INSTALLED
    if _INSTALLED:
        return

    def alias_aware_upsert(conn: Any, **kwargs: Any) -> str:
        values = dict(kwargs)
        values["artist"] = resolve_artist(conn, values.get("artist", ""))
        return _ORIGINAL_UPSERT(conn, **values)

    store.upsert_recording = alias_aware_upsert
    _INSTALLED = True
