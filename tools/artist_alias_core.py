#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent artist-name canonicalization shared by Avachin runtimes.

The alias table is local SQLite state. It contains no provider credentials and
never triggers network access. Compact keys deliberately ignore spacing and
punctuation so variants such as ``Moein Z`` and ``MoeinZ`` can be grouped, while
cross-script aliases remain explicit human decisions.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any

ALIAS_SCHEMA_VERSION = 1


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_artist(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def artist_alias_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_artist(value)).casefold()
    return "".join(character for character in text if character.isalnum())


def ensure_alias_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artist_aliases (
            alias_key TEXT PRIMARY KEY,
            alias_text TEXT NOT NULL,
            canonical_artist TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL DEFAULT 'human-review',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_artist_aliases_canonical
            ON artist_aliases(canonical_key, status);
        """
    )
    # schema_meta exists in every versioned fingerprint DB, but tests may call
    # this helper against an empty SQLite connection.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO schema_meta (key, value, updated_at)
        VALUES ('artist_alias_schema_version', ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (str(ALIAS_SCHEMA_VERSION), now_utc()),
    )


def resolve_artist(conn: sqlite3.Connection, artist: Any) -> str:
    original = clean_artist(artist)
    key = artist_alias_key(original)
    if not key:
        return original
    ensure_alias_schema(conn)
    row = conn.execute(
        """
        SELECT canonical_artist
        FROM artist_aliases
        WHERE alias_key = ? AND status = 'active'
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    return clean_artist(row[0]) if row is not None else original


def register_alias(
    conn: sqlite3.Connection,
    alias: Any,
    canonical_artist: Any,
    *,
    source: str = "human-review",
) -> dict[str, str]:
    alias_text = clean_artist(alias)
    canonical = clean_artist(canonical_artist)
    alias_key = artist_alias_key(alias_text)
    canonical_key = artist_alias_key(canonical)
    if not alias_key or not canonical_key:
        raise ValueError("artist alias and canonical artist must contain a real value")
    ensure_alias_schema(conn)
    timestamp = now_utc()
    conn.execute(
        """
        INSERT INTO artist_aliases (
            alias_key, alias_text, canonical_artist, canonical_key,
            status, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(alias_key) DO UPDATE SET
            alias_text = excluded.alias_text,
            canonical_artist = excluded.canonical_artist,
            canonical_key = excluded.canonical_key,
            status = 'active',
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            alias_key,
            alias_text,
            canonical,
            canonical_key,
            clean_artist(source) or "human-review",
            timestamp,
            timestamp,
        ),
    )
    return {
        "alias_key": alias_key,
        "alias_text": alias_text,
        "canonical_artist": canonical,
        "canonical_key": canonical_key,
    }
