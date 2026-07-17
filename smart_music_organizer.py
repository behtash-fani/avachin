#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smart Music Organizer v11.3 — Reliability gate + optional Spotify fallback/enrichment.

Main behavior:
- Recursively scans the selected music library.
- Processes MP3 files only.
- Organizes MP3 files into one canonical Artist folder by default.
- Keeps configured cover/lyrics sidecars with their album and protects other files.
- Cleans numeric prefixes from filenames and Title tags.
- Uses embedded IDs/tags, MusicBrainz + Apple, optional Spotify, and AcoustID fingerprint fallback.
- Detects the actual MP3 bitrate and writes it as a custom ID3 TXXX tag.
- Stores reports, cache, and undo manifests OUTSIDE the music library.
- Never asks for per-file confirmation.
- Never overwrites an existing file.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import requests
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
    from rapidfuzz import fuzz
except ImportError as exc:
    print(
        f"Missing dependency: {exc}\n"
        "Run setup.bat first.",
        file=sys.stderr,
    )
    raise SystemExit(2)


APP_NAME = "SmartMusicOrganizer"
APP_VERSION = "11.3"

MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
APPLE_SEARCH_URL = "https://itunes.apple.com/search"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"

MP3_EXTENSION = ".mp3"

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

LEADING_NUMBER_RE = re.compile(
    r"""
    ^\s*
    (?:
        (?:cd|disc|disk|track)\s*
    )?
    \d{1,3}
    (?:
        \s*[_./\\\-\s]\s*\d{1,3}
    ){0,3}
    \s*
    (?::\s+|[-–—]\s*|\s{2,})
    """,
    re.IGNORECASE | re.VERBOSE,
)

BRACKET_BITRATE_RE = re.compile(
    r"""
    [\(\[\{]\s*
    (?:mp3\s*)?
    (?:64|80|96|112|128|160|192|224|256|320)
    \s*(?:kbps|k)?
    \s*[\)\]\}]
    """,
    re.IGNORECASE | re.VERBOSE,
)

TRAILING_BITRATE_RE = re.compile(
    r"""
    \s*[-–—]?\s*
    (?:64|80|96|112|128|160|192|224|256|320)
    \s*(?:kbps|k)\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

TRAILING_JUNK_PATTERNS = [
    re.compile(
        r"\s*[-–—]\s*(?:official\s*(?:audio|video)?|lyrics?|lyric\s*video)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*[-–—]\s*(?:download(?:ed)?\s+from\b.*)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\s*\b(?:www\.[^\s]+|https?://[^\s]+)\s*$",
        re.IGNORECASE,
    ),
]

FEATURE_SPLIT_RE = re.compile(
    r"\s+(?:feat(?:uring)?\.?|ft\.?|with|vs\.?)\s+",
    re.IGNORECASE,
)

EXPLICIT_FEATURE_RE = re.compile(
    r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+",
    re.IGNORECASE,
)

COLLABORATION_SPLIT_RE = re.compile(
    r"\s+(?:feat(?:uring)?\.?|ft\.?|with|vs\.?|x)\s+"
    r"|\s*&\s*|\s+and\s+|\s*[,;/]\s*",
    re.IGNORECASE,
)

LEADING_ARTIST_INDEX_RE = re.compile(
    r"^\s*\d{1,4}\s*[._-]\s*",
    re.IGNORECASE,
)

SITE_OR_SOURCE_RE = re.compile(
    r"(?:https?://|www\.|"
    r"(?:listen2music|radiojavan|nex1music|upmusic|upmusics|"
    r"music-fa|musics-fa|downloadmusic|mytehranmusic)|"
    r"[A-Za-z0-9-]+\.(?:ir|com|net|org)\b)",
    re.IGNORECASE,
)

SITE_BRACKET_RE = re.compile(
    r"[\[({][^\])}]{0,160}"
    r"(?:https?://|www\.|[A-Za-z0-9-]+\.(?:ir|com|net|org)\b|"
    r"listen2music|radiojavan|nex1music|upmusic|upmusics)"
    r"[^\])}]{0,160}[\])}]",
    re.IGNORECASE,
)

TRAILING_DISC_RE = re.compile(
    r"\s*[\[(]\s*(?:disc|disk|cd)\s*\d+\s*[\])]\s*$",
    re.IGNORECASE,
)

PARENTHETICAL_AFFILIATION_RE = re.compile(
    r"^(.+?)\s*\(([^()]{2,80})\)\s*$"
)

# Generic source-brand shape used by many downloaded collections, for example
# "Artist - SomeMusicSite".  This intentionally does not contain any real
# artist or website names.  It only recognizes a trailing brand-like token.
CAMEL_SOURCE_SUFFIX_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9]{3,31}$"
)

DEFAULT_CONFIG = {
    "musicbrainz_contact": "",
    "apple_country": "US",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "default_artist": "",
    "min_confidence": 85,
    "verify_existing_tags_online": False,
    "move_non_mp3": True,
    "remove_empty_folders": True,
    "write_bitrate_tag": True,
    "other_files_folder": "_Other_Files",
    "unknown_artist_folder": "_Unknown Artist",
    "singles_folder": "Singles",
    "album_subfolders_enabled": True,
    "duplicates_folder": "Conflicts",
    "duplicate_handling": "delete_exact_audio",
    "collaboration_folder_min_tracks": 3,
    "collaboration_album_min_tracks": 2,
    "folder_granularity": "primary_identity",
    "allow_joint_artist_folders": False,
    "artist_folder_name_style": "display",
    "merge_similar_artist_names": True,
    "artist_name_merge_min_score": 86.0,
    "filename_artist_credit_style": "primary_with_guests_parentheses",
    "filename_guest_separator": " x ",
    "artist_role_intelligence": True,
    "prefer_supported_existing_artist": True,
    "prefer_provider_canonical_artist_name": True,
    "resolve_artist_identities_online": True,
    "artist_identity_mode": "smart",
    "artist_identity_lookup_min_tracks": 2,
    "artist_identity_lookup_limit": 30,
    "artist_identity_min_score": 92.0,
    "artist_identity_variant_min_score": 90.0,
    "artist_identity_time_budget_seconds": 12.0,
    "artist_identity_request_timeout_seconds": 5.0,
    "artist_identity_request_attempts": 1,
    "artist_aliases": {},
    "album_aliases": {},
    "preserve_artist_groups": [],
    "scan_workers": 1,
    "max_search_seeds": 2,
    "fast_accept_confidence": 97.0,
    "identification_cache_days": 90,
    "journal_fsync": True,
    "preserve_sidecars": True,
    "sidecar_extensions": [".jpg", ".jpeg", ".png", ".webp", ".lrc", ".cue", ".m3u", ".m3u8"],
    "fingerprint_duplicates": True,
    "treat_title_named_release_as_single": True,
    "collapse_single_release_albums": True,
    "album_trust_gate_enabled": True,
    "album_folder_min_tracks": 2,
    "album_title_similarity_single_threshold": 88.0,
    "trust_single_track_musicbrainz_album": True,
    "trust_single_track_local_registry_album": True,
    "allow_non_vocal_artist_folders": False,
    "non_vocal_review_folder": "Review - Non Vocal Artists",
    "acoustid_api_key": "",
    "fingerprint_identification_enabled": True,
    "fingerprint_when_uncertain": True,
    "fingerprint_min_score": 0.72,
    "free_first_mode": True,
    "online_providers": {
        "musicbrainz": True,
        "apple_itunes": True,
        "acoustid": True,
        "spotify": False,
        "deezer": False
    },
    "spotify_fallback_only": True,
    "spotify_safe_mode": True,
    "spotify_min_confidence": 92.0,
    "spotify_cache_days": 30,
    "spotify_search_limit": 10,
    "spotify_market": "",
    "local_registry_enabled": True,
    "artist_registry_files": [
        "reference_data/artists/iranian.json",
        "reference_data/artists/international.json"
    ],
    "track_registry_files": [
        "reference_data/tracks/iranian.json",
        "reference_data/tracks/international.json"
    ],
    "registry_confidence": 91.0,
    "registry_artist_match_min_score": 90.0,
    "registry_title_match_min_score": 92.0,
    "automatic_learning_enabled": True,
    "learning_registry_enabled": True,
    "learning_registry_min_confidence": 86.0,
    "learning_registry_auto_accept_confidence": 93.0,
    "auto_learn_from_folders": True,
    "auto_learn_from_tags": True,
    "auto_learn_min_tracks": 2,
    "auto_learn_alias_min_evidence": 2,
    "learn_unknown_folder_artists": True,
    "export_learning_contributions": True,
    "max_path_length": 240,
    "progress_every": 25,
    "skip_symlinks": True,
}



@dataclass
class Tags:
    title: Optional[str] = None
    artist: Optional[str] = None
    albumartist: Optional[str] = None
    album: Optional[str] = None
    date: Optional[str] = None
    tracknumber: Optional[str] = None
    discnumber: Optional[str] = None
    genre: Optional[str] = None
    composer: Optional[str] = None
    lyricist: Optional[str] = None
    isrc: Optional[str] = None
    musicbrainz_trackid: Optional[str] = None
    musicbrainz_artistid: Optional[str] = None
    musicbrainz_albumid: Optional[str] = None


@dataclass
class AudioInfo:
    tags: Tags
    duration_seconds: Optional[float] = None
    bitrate_bps: Optional[int] = None
    bitrate_mode: Optional[str] = None


@dataclass
class Seed:
    title: str
    artist: str
    source: str
    isrc: Optional[str] = None


@dataclass
class Candidate:
    source: str
    title: str
    artist: str
    album: Optional[str] = None
    album_artist: Optional[str] = None
    date: Optional[str] = None
    tracknumber: Optional[str] = None
    discnumber: Optional[str] = None
    genre: Optional[str] = None
    isrc: Optional[str] = None
    duration_ms: Optional[int] = None
    artwork_url: Optional[str] = None
    musicbrainz_recording_id: Optional[str] = None
    musicbrainz_artist_ids: list[str] = field(default_factory=list)
    musicbrainz_release_id: Optional[str] = None
    spotify_track_id: Optional[str] = None
    apple_track_id: Optional[str] = None
    confidence: float = 0.0
    title_similarity: float = 0.0
    artist_similarity: float = 0.0
    duration_similarity: float = 0.0
    consensus_sources: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    item_type: str
    source_path: str
    old_filename: str
    new_filename: Optional[str]
    status: str
    match_source: Optional[str]
    confidence: Optional[float]
    title: Optional[str]
    artist: Optional[str]
    artist_folder: Optional[str]
    filename_artist: Optional[str]
    album: Optional[str]
    album_folder: Optional[str]
    bitrate_kbps: Optional[int]
    bitrate_mode: Optional[str]
    consensus_sources: str
    folder_reason: Optional[str] = None
    final_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class TrackPlan:
    source: Path
    audio: AudioInfo
    candidate: Candidate
    lookup_errors: list[str] = field(default_factory=list)
    artist_folder: Optional[str] = None
    filename_artist: Optional[str] = None
    album_folder: Optional[str] = None
    target: Optional[Path] = None


@dataclass(frozen=True)
class ArtistRef:
    name: str
    key: str
    stable: bool = False


@dataclass(frozen=True)
class RegistryArtist:
    id: str
    canonical_name: str
    preferred_folder_name: str
    native_name: Optional[str] = None
    roles: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    musicbrainz_id: Optional[str] = None
    spotify_id: Optional[str] = None


@dataclass(frozen=True)
class RegistryTrack:
    id: str
    canonical_title: str
    artist_ids: tuple[str, ...]
    album: Optional[str] = None
    date: Optional[str] = None
    isrc: Optional[str] = None
    aliases: tuple[tuple[str, str], ...] = ()


class LearningRegistry:
    """Small local SQLite registry learned from the user's own library.

    JSON files stay the portable community seed data. This SQLite file is the
    user's private, continuously improving memory: aliases, folder evidence,
    source-noise cleanup, and cautious artist identities learned while scanning.
    """

    def __init__(self, path: Path, config: dict[str, Any]) -> None:
        self.path = path
        self.config = config
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS artists (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                preferred_folder_name TEXT NOT NULL,
                native_name TEXT,
                roles_json TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL DEFAULT 0,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                folder_allowed INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'auto',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS aliases (
                alias_key TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                artist_id TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'auto',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(artist_id) REFERENCES artists(id)
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label_key TEXT NOT NULL,
                label TEXT NOT NULL,
                kind TEXT NOT NULL,
                artist_id TEXT,
                title TEXT,
                album TEXT,
                path_hash TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_key TEXT NOT NULL,
                title TEXT NOT NULL,
                artist_id TEXT,
                album TEXT,
                duration_seconds REAL,
                isrc TEXT,
                fingerprint TEXT,
                path_hash TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_aliases_artist_id ON aliases(artist_id);
            CREATE INDEX IF NOT EXISTS idx_observations_label_key ON observations(label_key);
            CREATE INDEX IF NOT EXISTS idx_recordings_title_artist ON recordings(title_key, artist_id);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def artist_id_for_name(name: str) -> str:
        key = comparison_text(name).replace(" ", "-")
        key = re.sub(r"[^a-z0-9\-آ-ی]+", "", key, flags=re.IGNORECASE)
        return f"learned.{key or uuid.uuid4().hex[:12]}"

    def upsert_artist(
        self,
        canonical_name: str,
        aliases: Iterable[str],
        confidence: float,
        roles: Optional[Iterable[str]] = None,
        folder_allowed: bool = True,
        source: str = "auto-library-learning",
        evidence_count: int = 1,
    ) -> str:
        canonical_name = compact_spaces(canonical_name)
        preferred = format_artist_folder_name(
            canonical_name,
            False,
            self.config,
        )
        artist_id = self.artist_id_for_name(preferred)
        now = datetime.now(timezone.utc).isoformat()
        roles_json = json.dumps(list(roles or ["singer", "vocalist"]), ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO artists(id, canonical_name, preferred_folder_name, native_name, roles_json,
                                confidence, evidence_count, folder_allowed, source, created_at, updated_at)
            VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                canonical_name=excluded.canonical_name,
                preferred_folder_name=excluded.preferred_folder_name,
                roles_json=excluded.roles_json,
                confidence=max(artists.confidence, excluded.confidence),
                evidence_count=artists.evidence_count + excluded.evidence_count,
                folder_allowed=CASE WHEN artists.folder_allowed=0 THEN 0 ELSE excluded.folder_allowed END,
                updated_at=excluded.updated_at
            """,
            (
                artist_id,
                canonical_name,
                preferred,
                roles_json,
                float(confidence),
                int(evidence_count),
                1 if folder_allowed else 0,
                source,
                now,
                now,
            ),
        )
        for alias in dict.fromkeys([canonical_name, preferred, *aliases]):
            self.upsert_alias(alias, artist_id, confidence, source, evidence_count)
        self.conn.commit()
        return artist_id

    def upsert_alias(
        self,
        alias: str,
        artist_id: str,
        confidence: float,
        source: str,
        evidence_count: int = 1,
    ) -> None:
        alias = compact_spaces(alias)
        alias_key = comparison_text(alias)
        if not alias_key:
            return
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO aliases(alias_key, alias, artist_id, confidence, evidence_count, source, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias_key) DO UPDATE SET
                alias=CASE WHEN excluded.confidence >= aliases.confidence THEN excluded.alias ELSE aliases.alias END,
                artist_id=CASE WHEN excluded.confidence >= aliases.confidence THEN excluded.artist_id ELSE aliases.artist_id END,
                confidence=max(aliases.confidence, excluded.confidence),
                evidence_count=aliases.evidence_count + excluded.evidence_count,
                updated_at=excluded.updated_at
            """,
            (
                alias_key,
                alias,
                artist_id,
                float(confidence),
                int(evidence_count),
                source,
                now,
                now,
            ),
        )

    def add_observation(
        self,
        label: str,
        kind: str,
        artist_id: Optional[str],
        path: Path,
        confidence: float,
        title: Optional[str] = None,
        album: Optional[str] = None,
    ) -> None:
        label = compact_spaces(label)
        label_key = comparison_text(label)
        if not label_key:
            return
        now = datetime.now(timezone.utc).isoformat()
        path_hash = hashlib.sha256(str(path).encode("utf-8", "ignore")).hexdigest()
        self.conn.execute(
            """
            INSERT INTO observations(label_key, label, kind, artist_id, title, album, path_hash, confidence, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                label_key,
                label,
                kind,
                artist_id,
                title,
                album,
                path_hash,
                float(confidence),
                now,
            ),
        )

    def add_recording_observation(
        self,
        title: str,
        artist_id: Optional[str],
        album: Optional[str],
        duration_seconds: Optional[float],
        isrc: Optional[str],
        path: Path,
        confidence: float,
    ) -> None:
        title = compact_spaces(title)
        if not title:
            return
        now = datetime.now(timezone.utc).isoformat()
        path_hash = hashlib.sha256(str(path).encode("utf-8", "ignore")).hexdigest()
        self.conn.execute(
            """
            INSERT INTO recordings(title_key, title, artist_id, album, duration_seconds, isrc, fingerprint, path_hash, confidence, created_at)
            VALUES(?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                comparison_text(title),
                title,
                artist_id,
                album,
                duration_seconds,
                isrc,
                path_hash,
                float(confidence),
                now,
            ),
        )

    def learned_artists(self, min_confidence: float) -> list[RegistryArtist]:
        rows = self.conn.execute(
            """
            SELECT * FROM artists
            WHERE confidence >= ? AND folder_allowed = 1
            ORDER BY confidence DESC, evidence_count DESC
            """,
            (float(min_confidence),),
        ).fetchall()
        artists: list[RegistryArtist] = []
        for row in rows:
            try:
                roles = tuple(json.loads(row["roles_json"] or "[]"))
            except json.JSONDecodeError:
                roles = ()
            alias_rows = self.conn.execute(
                "SELECT alias FROM aliases WHERE artist_id=? AND confidence >= ?",
                (row["id"], float(min_confidence)),
            ).fetchall()
            artists.append(
                RegistryArtist(
                    id=str(row["id"]),
                    canonical_name=str(row["canonical_name"]),
                    preferred_folder_name=str(row["preferred_folder_name"]),
                    roles=roles,
                    aliases=tuple(str(alias_row["alias"]) for alias_row in alias_rows),
                )
            )
        return artists

    def export_contributions(self, output_dir: Path, min_confidence: float) -> dict[str, int]:
        output_dir.mkdir(parents=True, exist_ok=True)
        artists_path = output_dir / "artists.learned.jsonl"
        aliases_path = output_dir / "artist_aliases.learned.jsonl"
        recordings_path = output_dir / "recordings.learned.jsonl"

        artist_count = 0
        with artists_path.open("w", encoding="utf-8") as fh:
            for row in self.conn.execute(
                "SELECT * FROM artists WHERE confidence >= ? ORDER BY preferred_folder_name",
                (float(min_confidence),),
            ):
                artist_count += 1
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

        alias_count = 0
        with aliases_path.open("w", encoding="utf-8") as fh:
            for row in self.conn.execute(
                "SELECT * FROM aliases WHERE confidence >= ? ORDER BY artist_id, alias",
                (float(min_confidence),),
            ):
                alias_count += 1
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

        recording_count = 0
        with recordings_path.open("w", encoding="utf-8") as fh:
            for row in self.conn.execute(
                "SELECT * FROM recordings WHERE confidence >= ? ORDER BY artist_id, title",
                (float(min_confidence),),
            ):
                recording_count += 1
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

        return {
            "artists": artist_count,
            "aliases": alias_count,
            "recordings": recording_count,
        }


def artist_names_likely_same(left: str, right: str, min_score: float = 86.0) -> bool:
    """Conservatively detect spelling variants of the same Latin artist name.

    This is intentionally stricter than normal fuzzy matching: multi-word names
    must have the same token count, an almost identical first token, and a high
    overall score. It merges common transliteration/spelling variants without
    collapsing unrelated artists.
    """
    left_key = comparison_text(left)
    right_key = comparison_text(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = left_key.split()
    right_tokens = right_key.split()
    if len(left_tokens) != len(right_tokens):
        return False
    overall = similarity(left, right)
    if len(left_tokens) == 1:
        return overall >= 96.0
    first = similarity(left_tokens[0], right_tokens[0])
    last = similarity(left_tokens[-1], right_tokens[-1])
    return first >= 94.0 and last >= 78.0 and overall >= min_score


class LibraryProfile:
    """Library-wide artist identity and role statistics.

    Folder decisions deliberately operate on a *single performance identity*.
    Full track credits remain in the Artist tag and filename, while the folder
    resolver uses provider identities, album anchors, explicit feature syntax,
    existing tags, and library-wide role evidence to choose the primary artist.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}
        # Legacy exact-name statistics are retained for album/name casing.
        self.artist_variants: dict[str, Counter[str]] = defaultdict(Counter)
        self.artist_counts: Counter[str] = Counter()
        self.collaboration_counts: Counter[str] = Counter()
        self.collaboration_album_counts: Counter[tuple[str, str]] = Counter()
        self.album_variants: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

        # Identity-aware statistics. Stable provider IDs can merge aliases or
        # script variants without any hard-coded artist names.
        self.entity_variants: dict[str, Counter[str]] = defaultdict(Counter)
        self.name_to_entity_keys: dict[str, Counter[str]] = defaultdict(Counter)
        self.entity_solo_counts: Counter[str] = Counter()
        self.entity_album_anchor_counts: Counter[str] = Counter()
        self.entity_lead_counts: Counter[str] = Counter()
        self.entity_secondary_counts: Counter[str] = Counter()
        self.entity_provider_counts: Counter[str] = Counter()
        self.entity_total_counts: Counter[str] = Counter()

    def register_entity(self, ref: ArtistRef) -> None:
        name = compact_spaces(ref.name)
        if not meaningful_artist_label(name):
            return
        key = ref.key or f"name:{comparison_text(name)}"
        self.entity_variants[key][name] += 1
        self.name_to_entity_keys[comparison_text(name)][key] += 1
        self.entity_total_counts[key] += 1
        if ref.stable:
            self.entity_provider_counts[key] += 1

        name_key = comparison_text(name)
        self.artist_variants[name_key][name] += 1
        self.artist_counts[name_key] += 1

    def register_track(
        self,
        track_refs: list[ArtistRef],
        album_refs: list[ArtistRef],
    ) -> None:
        track_refs = dedupe_artist_refs(track_refs)
        album_refs = dedupe_artist_refs(album_refs)

        for index, ref in enumerate(track_refs):
            self.register_entity(ref)
            if index == 0:
                self.entity_lead_counts[ref.key] += 1
            else:
                self.entity_secondary_counts[ref.key] += 1

        if len(track_refs) == 1:
            self.entity_solo_counts[track_refs[0].key] += 1

        for ref in album_refs:
            self.register_entity(ref)
        if len(album_refs) == 1 and not is_various_artist(album_refs[0].name):
            self.entity_album_anchor_counts[album_refs[0].key] += 1

    def add_artist(
        self,
        artist: str,
        album: Optional[str] = None,
    ) -> None:
        key = comparison_text(artist)
        if not key:
            return

        self.register_entity(ArtistRef(artist, f"name:{key}", False))

        if has_collaboration_separator(artist):
            self.collaboration_counts[key] += 1
            if album:
                album_key = comparison_text(album)
                if album_key:
                    self.collaboration_album_counts[(key, album_key)] += 1

    def add_album(
        self,
        artist: str,
        album: str,
    ) -> None:
        artist_key = comparison_text(artist)
        album_key = comparison_text(album)
        if artist_key and album_key:
            self.album_variants[(artist_key, album_key)][album] += 1

    def best_identity_key_for_name(self, artist: str) -> Optional[str]:
        keys = self.name_to_entity_keys.get(comparison_text(artist))
        if not keys:
            return None
        return keys.most_common(1)[0][0]

    def canonical_artist(
        self,
        artist: str,
        identity_key: Optional[str] = None,
    ) -> str:
        key = identity_key or self.best_identity_key_for_name(artist)
        if key and str(key).startswith("registry:"):
            registry = self.config.get("_artist_registry") or {}
            artists = registry.get("artists_by_id") or {}
            registry_id = str(key).split(":", 1)[1]
            registry_artist = artists.get(registry_id)
            if registry_artist is not None:
                return registry_artist.preferred_folder_name or registry_artist.canonical_name

        registry_artist = registry_artist_for_label(artist, self.config)
        if registry_artist is not None:
            return registry_artist.preferred_folder_name or registry_artist.canonical_name

        candidate_variants: Counter[str] = Counter()
        if key:
            candidate_variants.update(self.entity_variants.get(key, Counter()))

        # Stable provider IDs are authoritative. For local/name-only identities,
        # merge conservative spelling/transliteration variants across the whole
        # library so one singer cannot create two folders.
        stable_identity = bool(key and not str(key).startswith("name:"))
        if (
            not stable_identity
            and bool(self.config.get("merge_similar_artist_names", True))
        ):
            threshold = float(self.config.get("artist_name_merge_min_score", 86.0))
            for other_key, variants in self.entity_variants.items():
                if other_key == key or not variants:
                    continue
                representative = variants.most_common(1)[0][0]
                if artist_names_likely_same(artist, representative, threshold):
                    candidate_variants.update(variants)

        if candidate_variants:
            # Prefer frequency, then a clean display spelling. Mixed/title-case
            # names beat all-lowercase and underscore-shaped downloader labels.
            def display_quality(name: str) -> tuple[int, int, int]:
                ascii_letters = [c for c in name if c.isascii() and c.isalpha()]
                has_upper = any(c.isupper() for c in ascii_letters)
                has_lower = any(c.islower() for c in ascii_letters)
                natural_case = int(bool(ascii_letters) and has_upper and has_lower)
                no_underscore = int("_" not in name)
                return natural_case, no_underscore, -len(name)

            ranked = sorted(
                candidate_variants.items(),
                key=lambda item: (item[1], *display_quality(item[0]), item[0].casefold()),
                reverse=True,
            )
            return registry_display_name(ranked[0][0], self.config)

        name_key = comparison_text(artist)
        variants = self.artist_variants.get(name_key)
        if not variants:
            return artist
        return variants.most_common(1)[0][0]

    def canonical_album(self, artist: str, album: str) -> str:
        key = (comparison_text(artist), comparison_text(album))
        variants = self.album_variants.get(key)
        if not variants:
            return album
        return variants.most_common(1)[0][0]

    def entity_authority(self, ref: ArtistRef) -> float:
        """Score how strongly an identity behaves like a primary performer."""
        key = ref.key
        solo = self.entity_solo_counts[key]
        album = self.entity_album_anchor_counts[key]
        lead = self.entity_lead_counts[key]
        secondary = self.entity_secondary_counts[key]
        provider = self.entity_provider_counts[key]

        return (
            10.0 * math.log1p(solo)
            + 12.0 * math.log1p(album)
            + 5.0 * math.log1p(lead)
            + 2.5 * math.log1p(provider)
            - 2.0 * math.log1p(max(0, secondary - lead))
        )

    def should_preserve_collaboration(
        self,
        artist: str,
        album: Optional[str],
        config: dict[str, Any],
    ) -> bool:
        # v8 defaults to coarse, primary-identity folders. Joint folders are
        # opt-in; provider-confirmed atomic groups are handled separately and
        # do not need this heuristic.
        if not bool(config.get("allow_joint_artist_folders", False)):
            return False

        preserved = {
            comparison_text(str(value))
            for value in config.get("preserve_artist_groups", [])
        }
        artist_key = comparison_text(artist)
        if artist_key in preserved:
            return True

        minimum_tracks = int(config.get("collaboration_folder_min_tracks", 3))
        if self.collaboration_counts[artist_key] >= minimum_tracks:
            return True

        if album:
            album_key = comparison_text(album)
            minimum_album_tracks = int(config.get("collaboration_album_min_tracks", 2))
            if self.collaboration_album_counts[(artist_key, album_key)] >= minimum_album_tracks:
                return True

        return False


class Cache:
    """Thread-safe persistent cache for API responses and identifications."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute("PRAGMA temp_store=MEMORY")
            self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS identification_cache (
                    cache_key TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self.db.commit()

    def _get_table(
        self,
        table: str,
        key: str,
        max_age_days: int,
    ) -> Optional[Any]:
        with self.lock:
            row = self.db.execute(
                f"SELECT created_at, payload FROM {table} WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None

        created_at, payload = row
        if time.time() - created_at > max_age_days * 86400:
            return None

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def _set_table(self, table: str, key: str, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            self.db.execute(
                f"""
                INSERT INTO {table}(cache_key, created_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    created_at = excluded.created_at,
                    payload = excluded.payload
                """,
                (key, int(time.time()), encoded),
            )
            self.db.commit()

    def get(self, key: str, max_age_days: int) -> Optional[Any]:
        return self._get_table("api_cache", key, max_age_days)

    def set(self, key: str, payload: Any) -> None:
        self._set_table("api_cache", key, payload)

    def get_identification(self, key: str, max_age_days: int) -> Optional[Any]:
        return self._get_table("identification_cache", key, max_age_days)

    def set_identification(self, key: str, payload: Any) -> None:
        self._set_table("identification_cache", key, payload)

    def close(self) -> None:
        with self.lock:
            self.db.close()


class CatalogClient:
    def __init__(
        self,
        cache: Cache,
        musicbrainz_contact: str,
        spotify_client_id: str,
        spotify_client_secret: str,
        apple_country: str,
        timeout: int = 30,
    ) -> None:
        self.cache = cache
        self.timeout = timeout
        self.apple_country = (apple_country or "US").upper()
        self.spotify_client_id = spotify_client_id.strip()
        self.spotify_client_secret = spotify_client_secret.strip()
        self.spotify_market = ""
        self.spotify_cache_days = 30
        self.spotify_search_limit = 10
        self.enable_musicbrainz_provider = True
        self.enable_apple_provider = True
        self.enable_spotify_provider = True
        self.enable_acoustid_provider = True

        contact = musicbrainz_contact.strip() or "personal-local-use"
        self.default_headers = {
            "User-Agent": f"{APP_NAME}/{APP_VERSION} ({contact})",
            "Accept": "application/json",
        }
        self.thread_local = threading.local()
        self.rate_locks = {
            "musicbrainz": threading.Lock(),
            "apple": threading.Lock(),
        }
        self.last_musicbrainz_request = 0.0
        self.last_apple_request = 0.0
        self.spotify_token: Optional[str] = None
        self.spotify_token_expiry = 0.0
        self.spotify_token_lock = threading.Lock()

    def session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.default_headers)
            self.thread_local.session = session
        return session

    @staticmethod
    def cache_key(prefix: str, method: str, url: str, params: Any) -> str:
        stable = json.dumps(
            {"method": method, "url": url, "params": params},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        return f"{prefix}:{digest}"

    @staticmethod
    def wait(last_request: float, minimum_interval: float) -> None:
        elapsed = time.monotonic() - last_request
        if elapsed < minimum_interval:
            time.sleep(minimum_interval - elapsed)

    def get_json(
        self,
        *,
        prefix: str,
        url: str,
        params: dict[str, Any],
        max_age_days: int,
        minimum_interval: float,
        headers: Optional[dict[str, str]] = None,
        attempts: int = 3,
        request_timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        key = self.cache_key(prefix, "GET", url, params)
        cached = self.cache.get(key, max_age_days)
        if cached is not None:
            return cached

        rate_lock = self.rate_locks.get(prefix)

        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                if rate_lock:
                    rate_lock.acquire()
                try:
                    if prefix == "musicbrainz":
                        self.wait(self.last_musicbrainz_request, minimum_interval)
                    elif prefix == "apple":
                        self.wait(self.last_apple_request, minimum_interval)

                    response = self.session().get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=(request_timeout or self.timeout),
                    )

                    if prefix == "musicbrainz":
                        self.last_musicbrainz_request = time.monotonic()
                    elif prefix == "apple":
                        self.last_apple_request = time.monotonic()
                finally:
                    if rate_lock:
                        rate_lock.release()

                if response.status_code in {429, 500, 502, 503, 504}:
                    if attempt + 1 >= attempts:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else float(2 ** attempt)
                    time.sleep(max(1.0, delay))
                    continue

                response.raise_for_status()
                payload = response.json()
                self.cache.set(key, payload)
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(float(2 ** attempt))

        raise RuntimeError(f"{prefix} request failed: {last_error}")

    def musicbrainz_search(
        self,
        title: str,
        artist: str,
        isrc: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if isrc:
            query = f'isrc:"{escape_lucene(isrc)}"'
        else:
            query = (
                f'recording:"{escape_lucene(title)}" '
                f'AND artist:"{escape_lucene(artist)}"'
            )

        payload = self.get_json(
            prefix="musicbrainz",
            url=f"{MUSICBRAINZ_BASE}/recording",
            params={"query": query, "fmt": "json", "limit": limit},
            max_age_days=60,
            minimum_interval=1.05,
        )
        return payload.get("recordings", []) or []

    def musicbrainz_artist_search(
        self,
        artist: str,
        limit: int = 5,
        request_timeout: Optional[float] = None,
        attempts: int = 3,
    ) -> list[dict[str, Any]]:
        payload = self.get_json(
            prefix="musicbrainz",
            url=f"{MUSICBRAINZ_BASE}/artist",
            params={
                "query": f'artist:"{escape_lucene(artist)}"',
                "fmt": "json",
                "limit": limit,
            },
            max_age_days=180,
            minimum_interval=1.05,
            request_timeout=request_timeout,
            attempts=attempts,
        )
        return payload.get("artists", []) or []

    def musicbrainz_recording(
        self,
        recording_id: str,
    ) -> Optional[dict[str, Any]]:
        try:
            return self.get_json(
                prefix="musicbrainz",
                url=f"{MUSICBRAINZ_BASE}/recording/{recording_id}",
                params={
                    "fmt": "json",
                    "inc": "artists+releases+release-groups+isrcs",
                },
                max_age_days=90,
                minimum_interval=1.05,
            )
        except Exception:
            return None

    def apple_search(
        self,
        title: str,
        artist: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        payload = self.get_json(
            prefix="apple",
            url=APPLE_SEARCH_URL,
            params={
                "term": f"{title} {artist}",
                "media": "music",
                "entity": "song",
                "attribute": "songTerm",
                "country": self.apple_country,
                "limit": limit,
            },
            max_age_days=14,
            minimum_interval=0.15,
        )
        return payload.get("results", []) or []

    def acoustid_lookup(
        self,
        api_key: str,
        duration: int,
        fingerprint: str,
    ) -> dict[str, Any]:
        return self.get_json(
            prefix="acoustid",
            url=ACOUSTID_LOOKUP_URL,
            params={
                "client": api_key,
                "duration": duration,
                "fingerprint": fingerprint,
                "meta": "recordings+releasegroups+releases+tracks+compress",
                "format": "json",
            },
            max_age_days=180,
            minimum_interval=0.0,
        )

    def spotify_enabled(self) -> bool:
        enabled = getattr(self, "enable_spotify_provider", True)
        return bool(enabled and self.spotify_client_id and self.spotify_client_secret)

    def get_spotify_token(self) -> str:
        with self.spotify_token_lock:
            if self.spotify_token and time.time() < self.spotify_token_expiry - 60:
                return self.spotify_token

            credentials = (
                f"{self.spotify_client_id}:{self.spotify_client_secret}"
            ).encode("utf-8")
            authorization = base64.b64encode(credentials).decode("ascii")

            response = self.session().post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {authorization}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            self.spotify_token = payload["access_token"]
            self.spotify_token_expiry = (
                time.time() + int(payload.get("expires_in", 3600))
            )
            return self.spotify_token

    def spotify_search(
        self,
        title: str,
        artist: str,
        isrc: Optional[str] = None,
        album: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Search Spotify as an optional catalog fallback.

        Spotify is not used as a mandatory source.  The caller decides whether
        this search is part of the primary provider race or only a last-resort
        fallback.  We cache every response and honor 429 Retry-After inside
        get_json(), so enabling this provider does not create aggressive API
        traffic.
        """
        if not self.spotify_enabled():
            return []

        actual_limit = max(1, min(50, int(limit or self.spotify_search_limit or 10)))
        if isrc:
            query = f"isrc:{isrc}"
        else:
            query = f'track:"{title}" artist:"{artist}"'
            if album:
                query += f' album:"{album}"'

        token = self.get_spotify_token()
        params: dict[str, Any] = {
            "q": query,
            "type": "track",
            "limit": actual_limit,
        }
        market = str(getattr(self, "spotify_market", "") or "").strip().upper()
        if market:
            params["market"] = market

        payload = self.get_json(
            prefix="spotify",
            url=SPOTIFY_SEARCH_URL,
            params=params,
            max_age_days=max(1, int(getattr(self, "spotify_cache_days", 30) or 30)),
            minimum_interval=0.0,
            headers={"Authorization": f"Bearer {token}"},
        )
        return payload.get("tracks", {}).get("items", []) or []




def configure_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME

    return Path.home() / f".{APP_NAME.lower()}"


def select_folder_gui(title: str) -> Optional[Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title=title)
        root.destroy()
        return Path(selected) if selected else None
    except Exception:
        return None


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(
    value: str,
    normalize_persian: bool = False,
) -> str:
    value = unicodedata.normalize("NFC", value)
    value = (
        value.replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
    )
    if normalize_persian:
        value = value.translate(
            str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
        )
    return compact_spaces(value)


def comparison_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(
        str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
    )
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()


def similarity(left: Optional[str], right: Optional[str]) -> float:
    if not left or not right:
        return 0.0
    return float(
        fuzz.WRatio(
            comparison_text(left),
            comparison_text(right),
        )
    )


def provider_enabled(config: dict[str, Any], name: str, default: bool = True) -> bool:
    providers = config.get("online_providers")
    if isinstance(providers, dict) and name in providers:
        return bool(providers.get(name))
    return default


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _registry_path(script_dir: Path, value: str) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else script_dir / path


def load_artist_registry(script_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    artists_by_id: dict[str, RegistryArtist] = {}
    aliases: dict[str, str] = {}
    provider_ids: dict[str, str] = {}

    if not bool(config.get("local_registry_enabled", True)):
        return {"artists_by_id": artists_by_id, "aliases": aliases, "provider_ids": provider_ids}

    files = config.get("artist_registry_files") or []
    if not isinstance(files, list):
        files = []

    for file_name in files:
        payload = _read_json_file(_registry_path(script_dir, str(file_name)))
        if isinstance(payload, dict):
            entries = payload.get("artists") or []
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []

        for raw in entries:
            if not isinstance(raw, dict):
                continue
            artist_id = compact_spaces(str(raw.get("id") or ""))
            canonical = compact_spaces(str(raw.get("canonical_name") or raw.get("name") or ""))
            if not artist_id or not canonical:
                continue
            preferred = compact_spaces(str(raw.get("preferred_folder_name") or canonical))
            native = raw.get("native_name")
            aliases_raw = raw.get("aliases") or []
            roles_raw = raw.get("roles") or []
            artist = RegistryArtist(
                id=artist_id,
                canonical_name=canonical,
                preferred_folder_name=preferred,
                native_name=compact_spaces(str(native)) if native else None,
                roles=tuple(str(value) for value in roles_raw if str(value).strip()),
                aliases=tuple(str(value) for value in aliases_raw if str(value).strip()),
                musicbrainz_id=(str(raw.get("musicbrainz_id")) if raw.get("musicbrainz_id") else None),
                spotify_id=(str(raw.get("spotify_id")) if raw.get("spotify_id") else None),
            )
            artists_by_id[artist.id] = artist
            labels = [artist.canonical_name, artist.preferred_folder_name, *(artist.aliases or ())]
            if artist.native_name:
                labels.append(artist.native_name)
            for label in labels:
                key = comparison_text(label)
                if key:
                    aliases[key] = artist.id
            if artist.musicbrainz_id:
                provider_ids[f"mb:{artist.musicbrainz_id}"] = artist.id
            if artist.spotify_id:
                provider_ids[f"spotify:{artist.spotify_id}"] = artist.id

    return {"artists_by_id": artists_by_id, "aliases": aliases, "provider_ids": provider_ids}


def load_track_registry(script_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    tracks_by_key: dict[tuple[str, str], RegistryTrack] = {}
    tracks_by_isrc: dict[str, RegistryTrack] = {}

    if not bool(config.get("local_registry_enabled", True)):
        return {"tracks_by_key": tracks_by_key, "tracks_by_isrc": tracks_by_isrc}

    artist_registry = config.get("_artist_registry") or {}
    aliases = artist_registry.get("aliases") or {}
    files = config.get("track_registry_files") or []
    if not isinstance(files, list):
        files = []

    def artist_id_for_label(label: str) -> Optional[str]:
        return aliases.get(comparison_text(label))

    for file_name in files:
        payload = _read_json_file(_registry_path(script_dir, str(file_name)))
        if isinstance(payload, dict):
            entries = payload.get("tracks") or []
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []

        for raw in entries:
            if not isinstance(raw, dict):
                continue
            track_id = compact_spaces(str(raw.get("id") or ""))
            title = compact_spaces(str(raw.get("canonical_title") or raw.get("title") or ""))
            raw_artists = raw.get("artist_ids") or raw.get("artists") or []
            artist_ids = tuple(str(value) for value in raw_artists if str(value).strip())
            if not track_id or not title or not artist_ids:
                continue
            alias_pairs: list[tuple[str, str]] = []
            for alias in raw.get("aliases") or []:
                if isinstance(alias, dict):
                    alias_title = compact_spaces(str(alias.get("title") or ""))
                    alias_artist = compact_spaces(str(alias.get("artist") or ""))
                    if alias_title and alias_artist:
                        alias_pairs.append((alias_title, alias_artist))
            track = RegistryTrack(
                id=track_id,
                canonical_title=title,
                artist_ids=artist_ids,
                album=(compact_spaces(str(raw.get("album"))) if raw.get("album") else None),
                date=(str(raw.get("date")) if raw.get("date") else None),
                isrc=(str(raw.get("isrc")) if raw.get("isrc") else None),
                aliases=tuple(alias_pairs),
            )
            if track.isrc:
                tracks_by_isrc[comparison_text(track.isrc)] = track
            for artist_id in artist_ids:
                tracks_by_key[(comparison_text(title), artist_id)] = track
            for alias_title, alias_artist in alias_pairs:
                artist_id = artist_id_for_label(alias_artist)
                if artist_id:
                    tracks_by_key[(comparison_text(alias_title), artist_id)] = track

    return {"tracks_by_key": tracks_by_key, "tracks_by_isrc": tracks_by_isrc}


def load_local_registries(script_dir: Path, config: dict[str, Any]) -> None:
    artist_registry = load_artist_registry(script_dir, config)
    config["_artist_registry"] = artist_registry
    config["_track_registry"] = load_track_registry(script_dir, config)


def merge_learning_registry_into_config(
    learning: Optional[LearningRegistry],
    config: dict[str, Any],
) -> int:
    """Expose high-confidence learned identities through normal registry lookup."""
    if learning is None or not bool(config.get("learning_registry_enabled", True)):
        return 0
    artist_registry = config.setdefault(
        "_artist_registry",
        {"artists_by_id": {}, "aliases": {}, "provider_ids": {}},
    )
    artists_by_id = artist_registry.setdefault("artists_by_id", {})
    aliases = artist_registry.setdefault("aliases", {})
    min_confidence = float(config.get("learning_registry_min_confidence", 86.0))
    learned = learning.learned_artists(min_confidence)
    for artist in learned:
        artists_by_id[artist.id] = artist
        labels = [artist.canonical_name, artist.preferred_folder_name, *(artist.aliases or ())]
        if artist.native_name:
            labels.append(artist.native_name)
        for label in labels:
            key = comparison_text(label)
            if key:
                aliases.setdefault(key, artist.id)

    # Learned aliases may point at bundled JSON artist IDs as well. This lets
    # one user's library teach that "Arman Garshasbi~ UpMusic" is the bundled
    # artist "ir.arman-garshasbi" without duplicating the artist row itself.
    try:
        rows = learning.conn.execute(
            "SELECT alias_key, artist_id FROM aliases WHERE confidence >= ?",
            (float(min_confidence),),
        ).fetchall()
        for row in rows:
            artist_id = str(row["artist_id"])
            if artist_id in artists_by_id:
                aliases.setdefault(str(row["alias_key"]), artist_id)
    except sqlite3.Error:
        pass
    return len(learned)


def existing_registry_artist_for_any_label(
    labels: Iterable[str],
    config: dict[str, Any],
) -> Optional[RegistryArtist]:
    for label in labels:
        artist = registry_artist_for_label(label, config)
        if artist is not None:
            return artist
    return None


def best_display_label(labels: Iterable[str], config: dict[str, Any]) -> str:
    cleaned = [compact_spaces(label) for label in labels if compact_spaces(label)]
    if not cleaned:
        return "Unknown Artist"

    def quality(label: str) -> tuple[int, int, int, int]:
        text = format_artist_folder_name(label, False, config)
        latin = bool(re.search(r"[A-Za-z]", text))
        natural = bool(re.search(r"[A-Z]", text) and re.search(r"[a-z]", text))
        no_noise = not bool(SITE_OR_SOURCE_RE.search(text))
        return (int(no_noise), int(natural), int(latin), len(text))

    return max(cleaned, key=quality)


def candidate_folder_artist_from_path(
    input_root: Path,
    source: Path,
    normalize_persian: bool,
    config: dict[str, Any],
) -> Optional[str]:
    try:
        relative = source.relative_to(input_root)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    first = relative.parts[0]
    protected = {
        comparison_text(str(config.get("other_files_folder", "_Other_Files"))),
        comparison_text(str(config.get("unknown_artist_folder", "_Unknown Artist"))),
        comparison_text(str(config.get("duplicates_folder", "Conflicts"))),
        comparison_text(str(config.get("non_vocal_review_folder", "Review - Non Vocal Artists"))),
        "review",
        "unknown",
        "conflicts",
        "singles",
    }
    if comparison_text(first) in protected:
        return None
    cleaned = clean_artist_label(first, normalize_persian, config)
    if not meaningful_artist_label(cleaned):
        return None
    return cleaned


def auto_learn_from_library(
    input_root: Path,
    mp3_files: list[Path],
    audio_cache: dict[Path, AudioInfo],
    normalize_persian: bool,
    config: dict[str, Any],
    learning: Optional[LearningRegistry],
    run_dir: Path,
) -> dict[str, int]:
    """Learn high-confidence aliases from the current library before planning.

    The learner never trusts one weak signal. It combines existing folders,
    Album Artist/Artist tags, local JSON identities, and source-noise cleanup.
    Unknown candidates below the configured evidence threshold remain only as
    observations and exported suggestions; they do not affect the current run.
    """
    if learning is None or not bool(config.get("automatic_learning_enabled", True)):
        return {"artists": 0, "aliases": 0, "observations": 0, "recordings": 0}

    groups: dict[str, dict[str, Any]] = {}
    observations = 0
    recordings = 0
    min_tracks = max(1, int(config.get("auto_learn_min_tracks", 2)))
    allow_unknown = bool(config.get("learn_unknown_folder_artists", True))

    for source in mp3_files:
        audio = audio_cache.get(source)
        if audio is None:
            continue
        title = clean_title(audio.tags.title or source.stem, normalize_persian)
        album = clean_album_label(audio.tags.album, title, normalize_persian, config)

        labels: list[str] = []
        folder_artist = None
        if bool(config.get("auto_learn_from_folders", True)):
            folder_artist = candidate_folder_artist_from_path(input_root, source, normalize_persian, config)
            if folder_artist:
                labels.append(folder_artist)
        if bool(config.get("auto_learn_from_tags", True)):
            for raw in (audio.tags.albumartist, audio.tags.artist):
                cleaned = clean_artist_label(raw, normalize_persian, config)
                if meaningful_artist_label(cleaned):
                    labels.append(first_primary_artist(cleaned))

        labels = [label for label in dict.fromkeys(labels) if meaningful_artist_label(label)]
        if not labels:
            continue

        registry_artist = existing_registry_artist_for_any_label(labels, config)
        folder_allowed = True
        if registry_artist is not None:
            canonical = registry_artist.preferred_folder_name or registry_artist.canonical_name
            artist_id = f"registry:{registry_artist.id}"
            folder_allowed = registry_artist_has_vocal_role(registry_artist)
        elif allow_unknown:
            canonical = best_display_label(labels, config)
            artist_id = LearningRegistry.artist_id_for_name(canonical)
        else:
            canonical = best_display_label(labels, config)
            artist_id = None

        key = comparison_text(canonical)
        if not key:
            continue
        group = groups.setdefault(
            key,
            {
                "canonical": canonical,
                "aliases": Counter(),
                "tracks": set(),
                "registry_artist": registry_artist,
                "folder_allowed": folder_allowed,
            },
        )
        group["tracks"].add(str(source))
        for label in labels:
            group["aliases"][label] += 1
            learning.add_observation(
                label=label,
                kind="folder-or-tag-artist",
                artist_id=artist_id,
                path=source,
                confidence=88.0 if registry_artist is None else 97.0,
                title=title,
                album=album,
            )
            observations += 1
        if title:
            learning.add_recording_observation(
                title=title,
                artist_id=artist_id,
                album=album,
                duration_seconds=audio.duration_seconds,
                isrc=audio.tags.isrc,
                path=source,
                confidence=86.0 if registry_artist is None else 95.0,
            )
            recordings += 1

    learned_artists = 0
    learned_aliases = 0
    report_rows: list[dict[str, Any]] = []
    for group in groups.values():
        track_count = len(group["tracks"])
        aliases_counter: Counter[str] = group["aliases"]
        registry_artist = group["registry_artist"]
        folder_allowed = bool(group["folder_allowed"])
        if registry_artist is not None:
            confidence = 98.0
        else:
            confidence = 76.0 + min(17.0, track_count * 3.0)
        aliases = [alias for alias, count in aliases_counter.items() if count >= 1]
        accepted = track_count >= min_tracks and confidence >= float(
            config.get("learning_registry_min_confidence", 86.0)
        )
        if accepted:
            if registry_artist is not None:
                canonical = registry_artist.preferred_folder_name or registry_artist.canonical_name
                roles = registry_artist.roles
                artist_id = registry_artist.id
                # Known JSON artists are already in the normal registry. Only
                # add newly observed aliases to the learning database.
                for alias in aliases:
                    learning.upsert_alias(
                        alias,
                        artist_id,
                        confidence,
                        "auto-library-learning-known-artist",
                        aliases_counter[alias],
                    )
                    learned_aliases += 1
            else:
                canonical = format_artist_folder_name(str(group["canonical"]), normalize_persian, config)
                learning.upsert_artist(
                    canonical_name=canonical,
                    aliases=aliases,
                    confidence=confidence,
                    roles=["singer", "vocalist"],
                    folder_allowed=folder_allowed,
                    evidence_count=track_count,
                )
                learned_artists += 1
                learned_aliases += len(aliases)
        report_rows.append(
            {
                "canonical": str(group["canonical"]),
                "track_count": track_count,
                "confidence": round(confidence, 2),
                "accepted": accepted,
                "folder_allowed": folder_allowed,
                "aliases": sorted(aliases),
            }
        )

    try:
        learning.conn.commit()
        report_path = run_dir / "learning_report.json"
        report_path.write_text(
            json.dumps(report_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass

    return {
        "artists": learned_artists,
        "aliases": learned_aliases,
        "observations": observations,
        "recordings": recordings,
    }


def registry_artist_for_label(value: Optional[str], config: dict[str, Any]) -> Optional[RegistryArtist]:
    if not value:
        return None
    registry = config.get("_artist_registry") or {}
    aliases = registry.get("aliases") or {}
    artists = registry.get("artists_by_id") or {}
    artist_id = aliases.get(comparison_text(str(value)))
    return artists.get(artist_id) if artist_id else None


def registry_artist_for_provider_key(value: Optional[str], config: dict[str, Any]) -> Optional[RegistryArtist]:
    if not value:
        return None
    registry = config.get("_artist_registry") or {}
    provider_ids = registry.get("provider_ids") or {}
    artists = registry.get("artists_by_id") or {}
    artist_id = provider_ids.get(str(value))
    return artists.get(artist_id) if artist_id else None


def registry_artist_ref_for_label(value: str, config: dict[str, Any]) -> Optional[ArtistRef]:
    artist = registry_artist_for_label(value, config)
    if artist is None:
        return None
    return ArtistRef(
        name=artist.preferred_folder_name or artist.canonical_name,
        key=f"registry:{artist.id}",
        stable=True,
    )


def registry_display_name(value: str, config: dict[str, Any]) -> str:
    artist = registry_artist_for_label(value, config)
    if artist is None:
        return value
    return artist.preferred_folder_name or artist.canonical_name


VOCAL_REGISTRY_ROLES = {
    "singer",
    "vocalist",
    "vocals",
    "lead_vocals",
    "main_artist",
    "primary_artist",
    "rapper",
    "band",
    "group",
}

NON_VOCAL_REGISTRY_ROLES = {
    "composer",
    "lyricist",
    "songwriter",
    "writer",
    "arranger",
    "producer",
    "conductor",
    "instrumentalist",
    "pianist",
    "violinist",
    "guitarist",
}


def registry_artist_has_vocal_role(artist: Optional[RegistryArtist]) -> bool:
    if artist is None:
        return True
    roles = {comparison_text(role).replace(" ", "_") for role in artist.roles}
    if not roles:
        return True
    return bool(roles & VOCAL_REGISTRY_ROLES) or not bool(roles & NON_VOCAL_REGISTRY_ROLES)


def registry_artist_is_non_vocal_only(artist: Optional[RegistryArtist]) -> bool:
    if artist is None:
        return False
    roles = {comparison_text(role).replace(" ", "_") for role in artist.roles}
    return bool(roles & NON_VOCAL_REGISTRY_ROLES) and not bool(roles & VOCAL_REGISTRY_ROLES)


def ref_is_non_vocal_registry_only(ref: ArtistRef, config: dict[str, Any]) -> bool:
    if not str(ref.key).startswith("registry:"):
        return False
    registry = config.get("_artist_registry") or {}
    artists = registry.get("artists_by_id") or {}
    registry_id = str(ref.key).split(":", 1)[1]
    return registry_artist_is_non_vocal_only(artists.get(registry_id))


def escape_lucene(value: str) -> str:
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/])', r"\\\1", value)


def strip_leading_numbers(value: str) -> str:
    value = compact_spaces(value.replace("_", " "))
    previous = None
    while value != previous:
        previous = value
        value = LEADING_NUMBER_RE.sub("", value, count=1)
    return value.strip(" ._-")


def clean_title(
    value: str,
    normalize_persian: bool,
) -> str:
    value = normalize_text(value, normalize_persian)
    value = BRACKET_BITRATE_RE.sub("", value)
    value = TRAILING_BITRATE_RE.sub("", value)
    value = strip_leading_numbers(value)

    for pattern in TRAILING_JUNK_PATTERNS:
        value = pattern.sub("", value)

    value = re.sub(r"\s*[-–—]\s*", " - ", value)
    return compact_spaces(value).strip(" ._-")



def apply_alias(
    value: str,
    aliases: Any,
) -> str:
    if not isinstance(aliases, dict):
        return value

    value_key = comparison_text(value)
    for alias, canonical in aliases.items():
        if value_key == comparison_text(str(alias)):
            return str(canonical)

    return value


def contains_random_identifier(value: str) -> bool:
    text = value.strip()

    if re.match(
        r"^(?:19|20)\d{2}\s+[A-Za-z0-9_-]{8,}$",
        text,
    ):
        return True

    for token in re.findall(r"[A-Za-z0-9_-]+", text):
        if len(token) < 10:
            continue

        has_letter = bool(re.search(r"[A-Za-z]", token))
        has_digit = bool(re.search(r"\d", token))
        has_upper = bool(re.search(r"[A-Z]", token))
        has_lower = bool(re.search(r"[a-z]", token))

        if has_letter and has_digit and has_upper and has_lower:
            return True

    return False


def smart_latin_case(value: str) -> str:
    letters = re.sub(r"[^A-Za-z]+", "", value)
    if not letters:
        return value

    if value == value.lower():
        small_words = {"and", "of", "the", "de", "van", "von"}
        words = value.split()
        output: list[str] = []

        for index, word in enumerate(words):
            bare = re.sub(r"[^A-Za-z]", "", word).lower()
            if index > 0 and bare in small_words:
                output.append(word.lower())
            else:
                output.append(
                    word[:1].upper() + word[1:]
                    if word
                    else word
                )

        return " ".join(output)

    return value


def looks_like_source_brand(value: str) -> bool:
    """Return True for a generic trailing download/source brand token.

    The rule is structural rather than name-based: a single compact Latin
    token with an internal capital/digit pattern, or a token that already
    looks like a URL/source.  This avoids hard-coding specific websites while
    cleaning common tags such as ``Artist - SomeMusicSite``.
    """
    value = compact_spaces(value).strip("[]{}()<> ._-")
    if not value:
        return False
    if SITE_OR_SOURCE_RE.search(value):
        return True
    if not CAMEL_SOURCE_SUFFIX_RE.fullmatch(value):
        return False

    letters = re.sub(r"[^A-Za-z]", "", value)
    if len(letters) < 4:
        return False

    internal_upper = bool(re.search(r"[a-z][A-Z]", value))
    mixed_with_digits = bool(re.search(r"[A-Za-z]\d|\d[A-Za-z]", value))
    return internal_upper or mixed_with_digits


def strip_probable_source_suffix(value: str) -> str:
    """Remove a leading/trailing ``BrandToken -`` contamination from artist labels."""
    normalized = re.sub(r"\s*[~|]+\s*", " - ", value)
    parts = [compact_spaces(part) for part in normalized.split(" - ")]
    if len(parts) < 2:
        return value

    suffix = parts[-1]
    prefix = " - ".join(parts[:-1]).strip()
    if prefix and looks_like_source_brand(suffix):
        return prefix

    leading = parts[0]
    remainder = " - ".join(parts[1:]).strip()
    if remainder and looks_like_source_brand(leading):
        return remainder
    return value


def clean_artist_label(
    value: Optional[str],
    normalize_persian: bool,
    config: Optional[dict[str, Any]] = None,
) -> str:
    if not value:
        return ""

    config = config or DEFAULT_CONFIG
    raw = normalize_text(str(value), normalize_persian)
    had_handle = raw.lstrip().startswith("@")
    had_numeric_prefix = bool(
        LEADING_ARTIST_INDEX_RE.match(raw)
    )

    cleaned = SITE_BRACKET_RE.sub(" ", raw)
    cleaned = re.sub(r"^\s*@+\s*", "", cleaned)
    cleaned = LEADING_ARTIST_INDEX_RE.sub("", cleaned, count=1)
    cleaned = clean_title(cleaned, normalize_persian)
    cleaned = strip_probable_source_suffix(cleaned)
    cleaned = cleaned.strip("[]{}()<> ._-")

    # If the remaining text is itself a site/source label, reject it.
    if SITE_OR_SOURCE_RE.fullmatch(cleaned):
        return ""

    if SITE_OR_SOURCE_RE.search(cleaned):
        cleaned = SITE_OR_SOURCE_RE.sub(" ", cleaned)
        cleaned = compact_spaces(cleaned).strip("[]{}()<> ._-")

    # A common bad tag in downloaded Persian collections is 1.MoeinZ,
    # 4.MoeinZ, etc. Only remove the trailing Z when there was a numeric
    # source prefix, so legitimate names such as Jay-Z are not affected.
    if (
        had_numeric_prefix
        and re.fullmatch(r"[A-Za-z]{4,}Z", cleaned)
    ):
        cleaned = cleaned[:-1]

    cleaned = apply_alias(
        cleaned,
        config.get("artist_aliases", {}),
    )
    cleaned = compact_spaces(cleaned).strip("[]{}<> ._-")

    if had_handle or had_numeric_prefix:
        cleaned = smart_latin_case(cleaned)

    if contains_random_identifier(cleaned):
        return ""

    return cleaned


def meaningful_artist_label(value: Optional[str]) -> bool:
    if not value:
        return False

    text = compact_spaces(str(value))
    if invalid_tag(text):
        return False
    if SITE_OR_SOURCE_RE.search(text):
        return False
    if contains_random_identifier(text):
        return False

    letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
    return len(letters) >= 2


def meaningful_album_label(value: Optional[str]) -> bool:
    if not value:
        return False

    text = compact_spaces(str(value))
    key = comparison_text(text)

    if not key:
        return False
    if SITE_OR_SOURCE_RE.search(text):
        return False
    if contains_random_identifier(text):
        return False

    junk = {
        "unknown album",
        "unknown",
        "untitled",
        "no album",
        "misc",
        "miscellaneous",
        "music",
        "audio",
        "download",
        "single",
        "singles",
    }
    if key in junk:
        return False

    if re.fullmatch(r"\d{1,3}", key):
        return False

    return True


def clean_album_label(
    value: Optional[str],
    title: Optional[str],
    normalize_persian: bool,
    config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    if not value:
        return None

    config = config or DEFAULT_CONFIG
    cleaned = normalize_text(str(value), normalize_persian)
    cleaned = SITE_BRACKET_RE.sub(" ", cleaned)
    cleaned = clean_title(cleaned, normalize_persian)
    cleaned = TRAILING_DISC_RE.sub("", cleaned)
    cleaned = apply_alias(
        cleaned,
        config.get("album_aliases", {}),
    )
    cleaned = compact_spaces(cleaned).strip("[]{}<> ._-")

    if not meaningful_album_label(cleaned):
        return None

    # Album-vs-single decisions need library-wide context.  A title track of
    # a real album can have the same name as the album, while many Persian
    # catalog providers expose each single as a one-track release whose
    # collection title is just the song title.  Therefore this function only
    # cleans the label; ``reliable_album_folder_for`` decides whether it is
    # trusted enough to become a subfolder.
    return cleaned


def has_collaboration_separator(value: str) -> bool:
    return bool(COLLABORATION_SPLIT_RE.search(value))


def first_primary_artist(value: str) -> str:
    value = FEATURE_SPLIT_RE.split(value, maxsplit=1)[0]
    parts = [
        compact_spaces(part)
        for part in COLLABORATION_SPLIT_RE.split(value)
        if compact_spaces(part)
    ]
    primary = parts[0] if parts else value

    # "Amy Lee (Evanescence)" is an affiliation note, not a new artist.
    match = PARENTHETICAL_AFFILIATION_RE.match(primary)
    if match:
        primary = match.group(1)

    return compact_spaces(primary)


def is_various_artist(value: Optional[str]) -> bool:
    return comparison_text(str(value or "")) in {
        "various artists",
        "various",
        "va",
    }


def dedupe_artist_refs(refs: Iterable[ArtistRef]) -> list[ArtistRef]:
    output: list[ArtistRef] = []
    seen: set[str] = set()
    for ref in refs:
        marker = ref.key or f"name:{comparison_text(ref.name)}"
        if not marker or marker in seen:
            continue
        seen.add(marker)
        output.append(ref)
    return output


def split_credit_entities(value: Optional[str]) -> list[str]:
    """Split a free-form multi-artist credit into individual identities.

    Provider-specific builders store structured entities, so this heuristic is
    mainly for existing/local tags. Provider-confirmed groups with separators
    remain atomic because their structured evidence bypasses this function.
    """
    if not value:
        return []
    value = compact_spaces(value)
    if not value:
        return []

    parts = [
        compact_spaces(part)
        for part in COLLABORATION_SPLIT_RE.split(value)
        if compact_spaces(part)
    ]
    return parts or [value]


def artist_refs_from_names(
    names: Iterable[str],
    keys: Optional[Iterable[str]] = None,
    normalize_persian: bool = False,
    config: Optional[dict[str, Any]] = None,
) -> list[ArtistRef]:
    config = config or DEFAULT_CONFIG
    raw_keys = list(keys or [])
    refs: list[ArtistRef] = []
    for index, raw_name in enumerate(names):
        name = clean_artist_label(raw_name, normalize_persian, config)
        if not meaningful_artist_label(name):
            continue
        raw_key = str(raw_keys[index]) if index < len(raw_keys) else ""
        registry_by_provider = registry_artist_for_provider_key(raw_key, config)
        registry_by_name = registry_artist_for_label(name, config)
        registry_artist = registry_by_provider or registry_by_name
        if registry_artist is not None:
            name = registry_artist.preferred_folder_name or registry_artist.canonical_name
            key = f"registry:{registry_artist.id}"
            stable = True
        else:
            stable = bool(raw_key and not raw_key.startswith("name:"))
            key = raw_key if raw_key else f"name:{comparison_text(name)}"
        refs.append(ArtistRef(name=name, key=key, stable=stable))
    return dedupe_artist_refs(refs)


def candidate_artist_refs(
    candidate: Candidate,
    album: bool,
    normalize_persian: bool,
    config: dict[str, Any],
) -> list[ArtistRef]:
    prefix = "album_artist" if album else "track_artist"
    names = candidate.evidence.get(f"{prefix}_entities")
    keys = candidate.evidence.get(f"{prefix}_keys")
    if isinstance(names, list) and names:
        return artist_refs_from_names(
            [str(value) for value in names],
            [str(value) for value in keys] if isinstance(keys, list) else None,
            normalize_persian,
            config,
        )

    raw = candidate.album_artist if album else candidate.artist
    cleaned = clean_artist_label(raw, normalize_persian, config)
    names = split_credit_entities(cleaned)
    return artist_refs_from_names(names, None, normalize_persian, config)


def text_artist_refs(
    value: Optional[str],
    normalize_persian: bool,
    config: dict[str, Any],
) -> list[ArtistRef]:
    cleaned = clean_artist_label(value, normalize_persian, config)
    return artist_refs_from_names(
        split_credit_entities(cleaned),
        None,
        normalize_persian,
        config,
    )


def explicit_feature_primary_name(
    value: Optional[str],
    normalize_persian: bool,
    config: dict[str, Any],
) -> Optional[str]:
    if not value or not EXPLICIT_FEATURE_RE.search(value):
        return None
    primary = EXPLICIT_FEATURE_RE.split(value, maxsplit=1)[0]
    cleaned = clean_artist_label(primary, normalize_persian, config)
    return cleaned if meaningful_artist_label(cleaned) else None


def ref_matches_name(ref: ArtistRef, name: Optional[str]) -> bool:
    return bool(name and similarity(ref.name, name) >= 94)


def role_tag_names(
    tags: Tags,
    normalize_persian: bool,
    config: dict[str, Any],
) -> set[str]:
    output: set[str] = set()
    for value in (tags.composer, tags.lyricist):
        for ref in text_artist_refs(value, normalize_persian, config):
            output.add(comparison_text(ref.name))
    return output


def local_credit_evidence(
    track_artist: Optional[str],
    album_artist: Optional[str],
    normalize_persian: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    track_refs = text_artist_refs(track_artist, normalize_persian, config)
    album_refs = text_artist_refs(album_artist, normalize_persian, config)
    return {
        "track_artist_entities": [ref.name for ref in track_refs],
        "track_artist_keys": [ref.key for ref in track_refs],
        "track_artist_atomic": bool(
            len(track_refs) == 1 and not has_collaboration_separator(track_artist or "")
        ),
        "album_artist_entities": [ref.name for ref in album_refs],
        "album_artist_keys": [ref.key for ref in album_refs],
        "album_artist_atomic": bool(
            len(album_refs) == 1 and not has_collaboration_separator(album_artist or "")
        ),
    }


def first_tag(tags: Any, key: str) -> Optional[str]:
    try:
        value = tags.get(key)
    except Exception:
        return None

    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None

    text = compact_spaces(str(value))
    return text or None


def read_mp3(path: Path) -> AudioInfo:
    tags = Tags()
    duration: Optional[float] = None
    bitrate_bps: Optional[int] = None
    bitrate_mode: Optional[str] = None

    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return AudioInfo(tags=tags)

        if audio.tags is not None:
            tags = Tags(
                title=first_tag(audio.tags, "title"),
                artist=first_tag(audio.tags, "artist"),
                albumartist=first_tag(audio.tags, "albumartist"),
                album=first_tag(audio.tags, "album"),
                date=first_tag(audio.tags, "date"),
                tracknumber=first_tag(audio.tags, "tracknumber"),
                discnumber=first_tag(audio.tags, "discnumber"),
                genre=first_tag(audio.tags, "genre"),
                composer=first_tag(audio.tags, "composer"),
                lyricist=first_tag(audio.tags, "lyricist"),
                isrc=first_tag(audio.tags, "isrc"),
                musicbrainz_trackid=first_tag(
                    audio.tags,
                    "musicbrainz_trackid",
                ),
                musicbrainz_artistid=first_tag(
                    audio.tags,
                    "musicbrainz_artistid",
                ),
                musicbrainz_albumid=first_tag(
                    audio.tags,
                    "musicbrainz_albumid",
                ),
            )

        info = getattr(audio, "info", None)
        if info is not None:
            raw_duration = getattr(info, "length", None)
            if raw_duration:
                duration = float(raw_duration)

            raw_bitrate = getattr(info, "bitrate", None)
            if raw_bitrate:
                bitrate_bps = int(raw_bitrate)

            raw_mode = getattr(info, "bitrate_mode", None)
            if raw_mode is not None:
                bitrate_mode = str(raw_mode).split(".")[-1].upper()
    except Exception:
        pass

    return AudioInfo(
        tags=tags,
        duration_seconds=duration,
        bitrate_bps=bitrate_bps,
        bitrate_mode=bitrate_mode,
    )


def invalid_tag(value: Optional[str]) -> bool:
    if not value:
        return True

    key = comparison_text(value).replace(" ", "")
    invalid = {
        "unknown",
        "unknownartist",
        "untitled",
        "track",
        "audio",
        "mp3",
        "various",
        "variousartists",
        "ناشناخته",
    }
    return not key or key in invalid or bool(re.fullmatch(r"\d+", key))


def text_was_dirty(value: Optional[str]) -> bool:
    if not value:
        return True

    cleaned = clean_title(value, False)
    return comparison_text(cleaned) != comparison_text(value)


def generate_seeds(
    path: Path,
    tags: Tags,
    default_artist: Optional[str],
    normalize_persian: bool,
    config: Optional[dict[str, Any]] = None,
) -> list[Seed]:
    config = config or DEFAULT_CONFIG
    seeds: list[Seed] = []
    seen: set[tuple[str, str]] = set()

    def add(
        title: Optional[str],
        artist: Optional[str],
        source: str,
    ) -> None:
        if not title or not artist:
            return

        cleaned_title = clean_title(title, normalize_persian)
        cleaned_artist = clean_artist_label(
            artist,
            normalize_persian,
            config,
        )
        if (
            not cleaned_title
            or not meaningful_artist_label(cleaned_artist)
        ):
            return

        key = (
            comparison_text(cleaned_title),
            comparison_text(cleaned_artist),
        )
        if key in seen:
            return

        seen.add(key)
        seeds.append(
            Seed(
                title=cleaned_title,
                artist=cleaned_artist,
                source=source,
                isrc=tags.isrc,
            )
        )

    if not invalid_tag(tags.title) and not invalid_tag(tags.artist):
        add(tags.title, tags.artist, "existing-tags")

    stem = clean_title(path.stem, normalize_persian)
    parts = [
        compact_spaces(part)
        for part in stem.split(" - ")
        if compact_spaces(part)
    ]

    if default_artist:
        artist_key = comparison_text(default_artist)
        matching_indexes = [
            index
            for index, part in enumerate(parts)
            if comparison_text(part) == artist_key
        ]
        remaining = [
            part
            for index, part in enumerate(parts)
            if index not in matching_indexes
        ]

        if remaining:
            add(
                " - ".join(remaining),
                default_artist,
                "filename+default-artist",
            )

        if tags.title:
            add(
                tags.title,
                default_artist,
                "tag-title+default-artist",
            )

    if len(parts) >= 2:
        add(
            " - ".join(parts[:-1]),
            parts[-1],
            "filename-title-artist",
        )
        add(
            " - ".join(parts[1:]),
            parts[0],
            "filename-artist-title",
        )
    elif len(parts) == 1 and default_artist:
        add(
            parts[0],
            default_artist,
            "single-title+default-artist",
        )

    return seeds


def artist_credit_text(item: dict[str, Any]) -> str:
    credits = item.get("artist-credit") or []
    output: list[str] = []

    for credit in credits:
        if not isinstance(credit, dict):
            continue

        name = credit.get("name")
        if not name and isinstance(credit.get("artist"), dict):
            name = credit["artist"].get("name")

        if name:
            output.append(str(name))

        joinphrase = credit.get("joinphrase")
        if joinphrase:
            output.append(str(joinphrase))

    return compact_spaces("".join(output))


def artist_credit_ids(item: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for credit in item.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue

        artist = credit.get("artist")
        if isinstance(artist, dict) and artist.get("id"):
            ids.append(str(artist["id"]))

    return ids


def artist_credit_entities_and_keys(
    item: dict[str, Any],
) -> tuple[list[str], list[str]]:
    names: list[str] = []
    keys: list[str] = []
    for credit in item.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") if isinstance(credit.get("artist"), dict) else {}
        name = credit.get("name") or artist.get("name")
        if not name:
            continue
        names.append(str(name))
        artist_id = artist.get("id")
        keys.append(f"mb:{artist_id}" if artist_id else "")
    return names, keys


def choose_musicbrainz_release(
    releases: Iterable[dict[str, Any]],
    old_album: Optional[str],
    recording_artist: str,
) -> Optional[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []

    for release in releases:
        score = 0.0
        title = str(release.get("title") or "")
        status = str(release.get("status") or "").casefold()
        release_group = release.get("release-group") or {}
        primary_type = str(
            release_group.get("primary-type") or ""
        ).casefold()
        secondary_types = {
            str(value).casefold()
            for value in (
                release_group.get("secondary-types") or []
            )
        }

        if status == "official":
            score += 20
        if primary_type in {"album", "single", "ep"}:
            score += 15
        if "compilation" in secondary_types:
            score -= 25
        if old_album:
            score += 0.35 * similarity(title, old_album)

        release_artist = artist_credit_text(release)
        if release_artist:
            score += 0.20 * similarity(
                release_artist,
                recording_artist,
            )

        if re.match(r"^\d{4}", str(release.get("date") or "")):
            score += 3

        ranked.append((score, release))

    if not ranked:
        return None

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1]


def musicbrainz_candidate(
    recording: dict[str, Any],
    old_album: Optional[str],
) -> Candidate:
    title = str(recording.get("title") or "")
    artist = artist_credit_text(recording)
    track_names, track_keys = artist_credit_entities_and_keys(recording)

    release = choose_musicbrainz_release(
        recording.get("releases") or [],
        old_album,
        artist,
    )
    isrcs = recording.get("isrcs") or []

    length = recording.get("length")
    try:
        duration_ms = int(length) if length is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    album_names, album_keys = artist_credit_entities_and_keys(release or {})
    release_group = (release or {}).get("release-group") or {}
    release_primary_type = str(release_group.get("primary-type") or "")
    release_secondary_types = [str(value) for value in (release_group.get("secondary-types") or [])]
    release_track_count = None
    for count_key in ("track-count", "track_count", "medium-count", "medium_count"):
        try:
            if (release or {}).get(count_key) is not None:
                release_track_count = int((release or {}).get(count_key))
                break
        except (TypeError, ValueError):
            pass

    return Candidate(
        source="musicbrainz",
        title=title,
        artist=artist,
        album=(release or {}).get("title"),
        album_artist=artist_credit_text(release or {}) or artist,
        date=(release or {}).get("date"),
        isrc=str(isrcs[0]) if isrcs else None,
        duration_ms=duration_ms,
        musicbrainz_recording_id=recording.get("id"),
        musicbrainz_artist_ids=artist_credit_ids(recording),
        musicbrainz_release_id=(release or {}).get("id"),
        evidence={
            "musicbrainz_search_score": recording.get("score"),
            "track_artist_entities": track_names,
            "track_artist_keys": track_keys,
            "track_artist_atomic": len(track_names) == 1,
            "album_artist_entities": album_names,
            "album_artist_keys": album_keys,
            "album_artist_atomic": len(album_names) == 1,
            "release_primary_type": release_primary_type,
            "release_secondary_types": release_secondary_types,
            "release_track_count": release_track_count,
        },
    )


def apple_candidate(item: dict[str, Any]) -> Candidate:
    release_date = str(item.get("releaseDate") or "")
    if "T" in release_date:
        release_date = release_date.split("T", 1)[0]

    duration = item.get("trackTimeMillis")
    try:
        duration_ms = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    track_artist_name = str(item.get("artistName") or "")
    album_artist_name = str(
        item.get("collectionArtistName") or item.get("artistName") or ""
    )
    track_entities = split_credit_entities(track_artist_name)
    album_entities = split_credit_entities(album_artist_name)
    track_artist_id = item.get("artistId")
    album_artist_id = item.get("collectionArtistId") or track_artist_id

    track_keys = [
        f"apple:{track_artist_id}" if track_artist_id and len(track_entities) == 1 else ""
        for _ in track_entities
    ]
    album_keys = [
        f"apple:{album_artist_id}" if album_artist_id and len(album_entities) == 1 else ""
        for _ in album_entities
    ]

    return Candidate(
        source="apple",
        title=str(item.get("trackName") or ""),
        artist=str(item.get("artistName") or ""),
        album=item.get("collectionName"),
        album_artist=item.get("collectionArtistName")
        or item.get("artistName"),
        date=release_date or None,
        tracknumber=(
            str(item["trackNumber"])
            if item.get("trackNumber") is not None
            else None
        ),
        discnumber=(
            str(item["discNumber"])
            if item.get("discNumber") is not None
            else None
        ),
        genre=item.get("primaryGenreName"),
        duration_ms=duration_ms,
        apple_track_id=(
            str(item["trackId"])
            if item.get("trackId") is not None
            else None
        ),
        evidence={
            "track_artist_entities": track_entities,
            "track_artist_keys": track_keys,
            "track_artist_atomic": len(track_entities) == 1,
            "album_artist_entities": album_entities,
            "album_artist_keys": album_keys,
            "album_artist_atomic": len(album_entities) == 1,
            "release_primary_type": "single" if item.get("trackCount") == 1 else "album",
            "release_track_count": item.get("trackCount"),
            "apple_collection_id": item.get("collectionId"),
        },
    )


def spotify_candidate(item: dict[str, Any]) -> Candidate:
    album = item.get("album") or {}
    artists = [
        str(artist.get("name"))
        for artist in item.get("artists") or []
        if artist.get("name")
    ]
    artist_keys = [
        f"spotify:{artist.get('id')}" if artist.get("id") else ""
        for artist in item.get("artists") or []
        if artist.get("name")
    ]
    album_artists = [
        str(artist.get("name"))
        for artist in album.get("artists") or []
        if artist.get("name")
    ]
    album_artist_keys = [
        f"spotify:{artist.get('id')}" if artist.get("id") else ""
        for artist in album.get("artists") or []
        if artist.get("name")
    ]
    external_ids = item.get("external_ids") or {}

    duration = item.get("duration_ms")
    try:
        duration_ms = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    return Candidate(
        source="spotify",
        title=str(item.get("name") or ""),
        artist=", ".join(artists),
        album=album.get("name"),
        album_artist=", ".join(album_artists) or ", ".join(artists),
        date=album.get("release_date"),
        tracknumber=(
            str(item["track_number"])
            if item.get("track_number") is not None
            else None
        ),
        discnumber=(
            str(item["disc_number"])
            if item.get("disc_number") is not None
            else None
        ),
        isrc=external_ids.get("isrc"),
        duration_ms=duration_ms,
        spotify_track_id=item.get("id"),
        evidence={
            "track_artist_entities": artists,
            "track_artist_keys": artist_keys,
            "track_artist_atomic": len(artists) == 1,
            "album_artist_entities": album_artists,
            "album_artist_keys": album_artist_keys,
            "album_artist_atomic": len(album_artists) == 1,
            "release_primary_type": album.get("album_type"),
            "release_track_count": album.get("total_tracks"),
        },
    )


def duration_similarity(
    local_seconds: Optional[float],
    candidate_ms: Optional[int],
) -> float:
    if not local_seconds or not candidate_ms:
        return 55.0

    difference = abs(local_seconds - candidate_ms / 1000.0)

    if difference <= 1.5:
        return 100.0
    if difference <= 3:
        return 96.0
    if difference <= 5:
        return 90.0
    if difference <= 8:
        return 80.0
    if difference <= 12:
        return 65.0
    if difference <= 20:
        return 40.0
    if difference <= 35:
        return 15.0
    return 0.0


def artist_credit_match_info(
    candidate: Candidate,
    seed_artist: str,
) -> tuple[float, dict[str, Any]]:
    """Compare a seed performer with structured candidate credits."""
    raw_names = candidate.evidence.get("track_artist_entities")
    candidate_names = (
        [str(value) for value in raw_names]
        if isinstance(raw_names, list) and raw_names
        else split_credit_entities(candidate.artist)
    )
    seed_names = split_credit_entities(seed_artist)

    if not candidate_names or not seed_names:
        return similarity(candidate.artist, seed_artist), {}

    pairs: list[tuple[float, int, int]] = []
    for seed_index, seed_name in enumerate(seed_names):
        for candidate_index, candidate_name in enumerate(candidate_names):
            pairs.append(
                (
                    similarity(seed_name, candidate_name),
                    seed_index,
                    candidate_index,
                )
            )

    pairs.sort(key=lambda item: item[0], reverse=True)
    best_score, seed_index, candidate_index = pairs[0]
    whole_score = similarity(candidate.artist, seed_artist)
    score = max(best_score, whole_score)

    secondary_only = bool(
        len(seed_names) == 1
        and len(candidate_names) > 1
        and candidate_index > 0
        and similarity(seed_names[0], candidate_names[0]) < 78
    )
    if secondary_only:
        score = min(score, 84.0)
    elif len(seed_names) == 1 and candidate_index == 0:
        score = min(100.0, max(score, best_score + 2.0))

    return score, {
        "candidate_artist_count": len(candidate_names),
        "seed_artist_count": len(seed_names),
        "matched_candidate_artist_index": candidate_index,
        "matched_seed_artist_index": seed_index,
        "seed_matches_secondary_only": secondary_only,
    }


def best_seed_match(
    candidate: Candidate,
    seeds: list[Seed],
) -> tuple[float, float, Optional[Seed], dict[str, Any]]:
    ranked: list[tuple[float, float, float, Seed, dict[str, Any]]] = []

    for seed in seeds:
        title_score = similarity(candidate.title, seed.title)
        artist_score, artist_info = artist_credit_match_info(
            candidate,
            seed.artist,
        )
        combined = 0.56 * title_score + 0.44 * artist_score
        ranked.append(
            (
                combined,
                title_score,
                artist_score,
                seed,
                artist_info,
            )
        )

    if not ranked:
        return 0.0, 0.0, None, {}

    ranked.sort(key=lambda item: item[0], reverse=True)
    _, title_score, artist_score, seed, artist_info = ranked[0]
    return title_score, artist_score, seed, artist_info


def score_candidates(
    candidates: list[Candidate],
    seeds: list[Seed],
    local_duration: Optional[float],
) -> list[Candidate]:
    source_quality = {
        "musicbrainz": 91.0,
        "spotify": 95.0,
        "apple": 88.0,
    }

    for candidate in candidates:
        title_score, artist_score, seed, artist_info = best_seed_match(
            candidate,
            seeds,
        )
        d_score = duration_similarity(
            local_duration,
            candidate.duration_ms,
        )

        exact_isrc = bool(
            seed
            and seed.isrc
            and candidate.isrc
            and comparison_text(seed.isrc)
            == comparison_text(candidate.isrc)
        )

        confidence = (
            0.42 * title_score
            + 0.34 * artist_score
            + 0.16 * d_score
            + 0.08 * source_quality.get(candidate.source, 80.0)
        )

        if exact_isrc:
            confidence = max(confidence, 98.5)

        candidate.title_similarity = title_score
        candidate.artist_similarity = artist_score
        candidate.duration_similarity = d_score
        candidate.confidence = min(100.0, confidence)
        candidate.evidence["best_seed"] = (
            asdict(seed) if seed else None
        )
        candidate.evidence["exact_isrc"] = exact_isrc
        candidate.evidence.update(artist_info)

    for candidate in candidates:
        agreeing_sources = {candidate.source}

        for other in candidates:
            if other is candidate or other.source == candidate.source:
                continue

            if (
                similarity(candidate.title, other.title) >= 92
                and similarity(candidate.artist, other.artist) >= 90
                and (
                    not candidate.duration_ms
                    or not other.duration_ms
                    or abs(
                        candidate.duration_ms - other.duration_ms
                    ) <= 7000
                )
            ):
                agreeing_sources.add(other.source)

        candidate.consensus_sources = sorted(agreeing_sources)
        bonus = min(10.0, 5.0 * (len(agreeing_sources) - 1))
        candidate.confidence = min(
            100.0,
            candidate.confidence + bonus,
        )

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.confidence,
            len(candidate.consensus_sources),
            candidate.title_similarity,
            candidate.artist_similarity,
        ),
        reverse=True,
    )


def merge_consensus(
    winner: Candidate,
    candidates: list[Candidate],
) -> Candidate:
    related = [
        candidate
        for candidate in candidates
        if (
            similarity(winner.title, candidate.title) >= 92
            and similarity(winner.artist, candidate.artist) >= 90
        )
    ]

    source_priority = {
        "musicbrainz": 3,
        "spotify": 2,
        "apple": 1,
    }
    related.sort(
        key=lambda candidate: (
            source_priority.get(candidate.source, 0),
            candidate.confidence,
        ),
        reverse=True,
    )

    def first_value(attribute: str) -> Any:
        value = getattr(winner, attribute)
        if value not in (None, "", []):
            return value

        for candidate in related:
            value = getattr(candidate, attribute)
            if value not in (None, "", []):
                return value

        return value

    for attribute in (
        "album",
        "album_artist",
        "date",
        "tracknumber",
        "discnumber",
        "genre",
        "isrc",
        "musicbrainz_recording_id",
        "musicbrainz_artist_ids",
        "musicbrainz_release_id",
        "spotify_track_id",
        "apple_track_id",
    ):
        setattr(winner, attribute, first_value(attribute))

    for evidence_key in (
        "track_artist_entities",
        "track_artist_keys",
        "track_artist_atomic",
        "album_artist_entities",
        "album_artist_keys",
        "album_artist_atomic",
    ):
        if winner.evidence.get(evidence_key) not in (None, "", []):
            continue
        for candidate in related:
            value = candidate.evidence.get(evidence_key)
            if value not in (None, "", []):
                winner.evidence[evidence_key] = value
                break

    winner.consensus_sources = sorted(
        {candidate.source for candidate in related}
    )
    return winner


def identification_cache_key(
    audio: AudioInfo,
    seeds: list[Seed],
    max_seeds: int = 2,
) -> str:
    stable = {
        "duration": round(audio.duration_seconds or 0.0, 1),
        "musicbrainz_trackid": audio.tags.musicbrainz_trackid or "",
        "isrc": audio.tags.isrc or "",
        "seeds": [
            {
                "title": comparison_text(seed.title),
                "artist": comparison_text(seed.artist),
                "isrc": seed.isrc or "",
            }
            for seed in seeds[:max_seeds]
        ],
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def identify_fast_catalog(
    audio: AudioInfo,
    seeds: list[Seed],
    client: CatalogClient,
) -> tuple[Optional[Candidate], list[str]]:
    """Fast enrichment path for valid Title/Artist tracks missing only Album."""
    if not seeds:
        return None, []
    seed = seeds[0]
    candidates: list[Candidate] = []
    errors: list[str] = []
    jobs: dict[Any, str] = {}
    apple_enabled = bool(getattr(client, "enable_apple_provider", True))
    max_workers = (1 if apple_enabled else 0) + (1 if client.spotify_enabled() else 0)
    if max_workers <= 0:
        return None, []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        if apple_enabled:
            jobs[executor.submit(client.apple_search, seed.title, seed.artist)] = "Apple"
        if client.spotify_enabled():
            jobs[
                executor.submit(
                    client.spotify_search,
                    seed.title,
                    seed.artist,
                    seed.isrc,
                    audio.tags.album,
                )
            ] = "Spotify"
        for future in as_completed(jobs):
            provider = jobs[future]
            try:
                items = future.result()
                if provider == "Apple":
                    candidates.extend(
                        apple_candidate(item)
                        for item in items
                        if item.get("kind") == "song"
                    )
                else:
                    candidates.extend(spotify_candidate(item) for item in items)
            except Exception as exc:
                errors.append(f"{provider}: {exc}")

    if not candidates:
        return None, errors
    ranked = score_candidates(candidates, seeds, audio.duration_seconds)
    return merge_consensus(ranked[0], ranked), errors


def identify_online(
    audio: AudioInfo,
    seeds: list[Seed],
    client: CatalogClient,
    config: Optional[dict[str, Any]] = None,
) -> tuple[Optional[Candidate], list[str]]:
    """Identify a track with provider concurrency and persistent result cache."""
    config = config or DEFAULT_CONFIG
    max_seeds = max(1, int(config.get("max_search_seeds", 2)))
    base_cache_key = identification_cache_key(audio, seeds, max_seeds)
    cache_context = (
        f"{APP_VERSION}|{client.apple_country}|"
        f"spotify={int(client.spotify_enabled())}|{base_cache_key}"
    )
    cache_key = hashlib.sha256(cache_context.encode("utf-8")).hexdigest()
    cache_days = int(config.get("identification_cache_days", 90))
    cached = client.cache.get_identification(cache_key, cache_days)
    if isinstance(cached, dict):
        raw_candidate = cached.get("candidate")
        errors = list(cached.get("errors") or [])
        if isinstance(raw_candidate, dict):
            return Candidate(**raw_candidate), errors
        if raw_candidate is None:
            return None, errors

    candidates: list[Candidate] = []
    errors: list[str] = []
    spotify_fallback_only = bool(config.get("spotify_fallback_only", True))

    if audio.tags.musicbrainz_trackid:
        recording = client.musicbrainz_recording(
            audio.tags.musicbrainz_trackid
        )
        if recording:
            candidate = musicbrainz_candidate(
                recording,
                audio.tags.album,
            )
            candidate.confidence = 100.0
            candidate.consensus_sources = ["musicbrainz"]
            candidates.append(candidate)

    fast_accept = float(config.get("fast_accept_confidence", 97.0))

    for seed in seeds[:max_seeds]:
        jobs: dict[Any, str] = {}
        provider_count = (
            (1 if bool(getattr(client, "enable_musicbrainz_provider", True)) else 0)
            + (1 if bool(getattr(client, "enable_apple_provider", True)) else 0)
            + (1 if (client.spotify_enabled() and not spotify_fallback_only) else 0)
        )
        if provider_count <= 0:
            continue
        with ThreadPoolExecutor(max_workers=provider_count) as executor:
            if bool(getattr(client, "enable_musicbrainz_provider", True)):
                jobs[
                    executor.submit(
                        client.musicbrainz_search,
                        seed.title,
                        seed.artist,
                        seed.isrc,
                    )
                ] = "MusicBrainz"
            if bool(getattr(client, "enable_apple_provider", True)):
                jobs[
                    executor.submit(
                        client.apple_search,
                        seed.title,
                        seed.artist,
                    )
                ] = "Apple"
            if client.spotify_enabled() and not spotify_fallback_only:
                jobs[
                    executor.submit(
                        client.spotify_search,
                        seed.title,
                        seed.artist,
                        seed.isrc,
                        audio.tags.album,
                        int(config.get("spotify_search_limit", 10)),
                    )
                ] = "Spotify"

            for future in as_completed(jobs):
                provider = jobs[future]
                try:
                    items = future.result()
                    if provider == "MusicBrainz":
                        candidates.extend(
                            musicbrainz_candidate(item, audio.tags.album)
                            for item in items
                        )
                    elif provider == "Apple":
                        candidates.extend(
                            apple_candidate(item)
                            for item in items
                            if item.get("kind") == "song"
                        )
                    else:
                        candidates.extend(
                            spotify_candidate(item)
                            for item in items
                        )
                except Exception as exc:
                    errors.append(f"{provider}: {exc}")

        if candidates:
            ranked = score_candidates(
                candidates,
                seeds,
                audio.duration_seconds,
            )
            best = merge_consensus(ranked[0], ranked)
            if (
                best.confidence >= fast_accept
                and best.title_similarity >= 92
                and best.artist_similarity >= 90
            ):
                client.cache.set_identification(
                    cache_key,
                    {"candidate": asdict(best), "errors": errors},
                )
                return best, errors

    if not candidates and spotify_fallback_only and client.spotify_enabled():
        spotify_min_confidence = float(config.get("spotify_min_confidence", 92.0))
        spotify_items: list[dict[str, Any]] = []
        for seed in seeds[:max_seeds]:
            try:
                spotify_items.extend(
                    client.spotify_search(
                        seed.title,
                        seed.artist,
                        seed.isrc,
                        audio.tags.album,
                        int(config.get("spotify_search_limit", 10)),
                    )
                )
            except Exception as exc:
                errors.append(f"Spotify fallback: {exc}")
        if spotify_items:
            spotify_candidates = [spotify_candidate(item) for item in spotify_items]
            ranked_spotify = score_candidates(
                spotify_candidates,
                seeds,
                audio.duration_seconds,
            )
            if ranked_spotify:
                best_spotify = merge_consensus(ranked_spotify[0], ranked_spotify)
                best_spotify.evidence["spotify_fallback_only"] = True
                if (
                    best_spotify.confidence >= spotify_min_confidence
                    and (
                        best_spotify.title_similarity >= 82
                        or best_spotify.evidence.get("exact_isrc")
                    )
                    and (
                        best_spotify.artist_similarity >= 80
                        or best_spotify.evidence.get("exact_isrc")
                    )
                ):
                    candidates.append(best_spotify)
                else:
                    errors.append(
                        "Spotify fallback below trust threshold: "
                        f"confidence={best_spotify.confidence:.1f}, "
                        f"title={best_spotify.title_similarity:.1f}, "
                        f"artist={best_spotify.artist_similarity:.1f}"
                    )

    if not candidates:
        # Do not cache transient provider failures as a long-lived negative hit.
        if not errors:
            client.cache.set_identification(
                cache_key,
                {"candidate": None, "errors": []},
            )
        return None, errors

    ranked = score_candidates(
        candidates,
        seeds,
        audio.duration_seconds,
    )
    best = merge_consensus(ranked[0], ranked)
    client.cache.set_identification(
        cache_key,
        {"candidate": asdict(best), "errors": errors},
    )
    return best, errors


def candidate_from_existing_tags(
    audio: AudioInfo,
    normalize_persian: bool,
    config: Optional[dict[str, Any]] = None,
) -> Optional[Candidate]:
    config = config or DEFAULT_CONFIG
    title = clean_title(
        audio.tags.title or "",
        normalize_persian,
    )
    artist = clean_artist_label(
        audio.tags.artist,
        normalize_persian,
        config,
    )
    album_artist = clean_artist_label(
        audio.tags.albumartist,
        normalize_persian,
        config,
    )
    album = clean_album_label(
        audio.tags.album,
        title,
        normalize_persian,
        config,
    )

    if not title or not meaningful_artist_label(artist):
        return None

    final_album_artist = (
        album_artist
        if meaningful_artist_label(album_artist)
        else artist
    )
    evidence = local_credit_evidence(
        artist,
        final_album_artist,
        normalize_persian,
        config,
    )
    if audio.tags.musicbrainz_artistid:
        stable_key = f"mb:{audio.tags.musicbrainz_artistid}"
        # A single stored MusicBrainz artist ID is stronger evidence than
        # heuristic splitting of an artist name containing "&" or "and".
        # This preserves real groups as one identity without hard-coded names.
        evidence["track_artist_entities"] = [artist]
        evidence["track_artist_keys"] = [stable_key]
        evidence["track_artist_atomic"] = True
        if similarity(final_album_artist, artist) >= 92:
            evidence["album_artist_entities"] = [final_album_artist]
            evidence["album_artist_keys"] = [stable_key]
            evidence["album_artist_atomic"] = True

    return Candidate(
        source="existing-tags",
        title=title,
        artist=artist,
        album=album,
        album_artist=final_album_artist,
        date=audio.tags.date,
        tracknumber=audio.tags.tracknumber,
        discnumber=audio.tags.discnumber,
        genre=audio.tags.genre,
        isrc=audio.tags.isrc,
        musicbrainz_recording_id=audio.tags.musicbrainz_trackid,
        musicbrainz_artist_ids=(
            [audio.tags.musicbrainz_artistid]
            if audio.tags.musicbrainz_artistid
            else []
        ),
        musicbrainz_release_id=audio.tags.musicbrainz_albumid,
        confidence=94.0,
        consensus_sources=["existing-tags"],
        evidence=evidence,
    )


def local_registry_candidate(
    audio: AudioInfo,
    seeds: list[Seed],
    normalize_persian: bool,
    config: dict[str, Any],
) -> Optional[Candidate]:
    """Use bundled/user-maintained JSON references after online providers fail.

    The registry is intentionally a fallback. It makes the project reliable for
    under-covered collections such as Persian archives while keeping online
    providers as the first source of truth.
    """
    if not bool(config.get("local_registry_enabled", True)):
        return None

    track_registry = config.get("_track_registry") or {}
    artist_registry = config.get("_artist_registry") or {}
    tracks_by_key = track_registry.get("tracks_by_key") or {}
    tracks_by_isrc = track_registry.get("tracks_by_isrc") or {}
    artists_by_id = artist_registry.get("artists_by_id") or {}

    def build_candidate(track: RegistryTrack, matched_seed: Optional[Seed], reason: str) -> Optional[Candidate]:
        main_artist = artists_by_id.get(track.artist_ids[0]) if track.artist_ids else None
        if main_artist is None:
            return None
        guest_names = []
        for artist_id in track.artist_ids[1:]:
            artist = artists_by_id.get(artist_id)
            if artist is not None:
                guest_names.append(artist.preferred_folder_name or artist.canonical_name)
        main_name = main_artist.preferred_folder_name or main_artist.canonical_name
        artist_credit = main_name
        if guest_names:
            artist_credit = f"{main_name} feat. {' x '.join(guest_names)}"
        track_entities = [main_name, *guest_names]
        track_keys = [f"registry:{artist_id}" for artist_id in track.artist_ids]
        confidence = float(config.get("registry_confidence", 91.0))
        if matched_seed is not None:
            confidence = max(
                confidence,
                0.45 * similarity(matched_seed.title, track.canonical_title)
                + 0.45 * similarity(matched_seed.artist, main_name)
                + 10.0,
            )
        return Candidate(
            source="local-registry",
            title=track.canonical_title,
            artist=artist_credit,
            album=track.album,
            album_artist=main_name,
            date=track.date,
            isrc=track.isrc or audio.tags.isrc,
            confidence=min(96.0, confidence),
            title_similarity=(similarity(matched_seed.title, track.canonical_title) if matched_seed else 100.0),
            artist_similarity=(similarity(matched_seed.artist, main_name) if matched_seed else 100.0),
            consensus_sources=["local-registry"],
            evidence={
                "local_registry_track_id": track.id,
                "local_registry_reason": reason,
                "track_artist_entities": track_entities,
                "track_artist_keys": track_keys,
                "track_artist_atomic": len(track_entities) == 1,
                "album_artist_entities": [main_name],
                "album_artist_keys": [f"registry:{main_artist.id}"],
                "album_artist_atomic": True,
            },
        )

    isrc_key = comparison_text(audio.tags.isrc or "")
    if isrc_key and isrc_key in tracks_by_isrc:
        return build_candidate(tracks_by_isrc[isrc_key], None, "isrc")

    title_min = float(config.get("registry_title_match_min_score", 92.0))
    artist_min = float(config.get("registry_artist_match_min_score", 90.0))
    aliases = artist_registry.get("aliases") or {}
    best: Optional[tuple[float, Candidate]] = None

    for seed in seeds:
        seed_artist_id = aliases.get(comparison_text(seed.artist))
        candidates: list[RegistryTrack] = []
        if seed_artist_id:
            direct = tracks_by_key.get((comparison_text(seed.title), seed_artist_id))
            if direct is not None:
                candidates.append(direct)
        # If exact key lookup failed, scan the compact registry for fuzzy title
        # aliases under the same artist. This is still fast for the intended
        # local JSON fallback files.
        if not candidates and seed_artist_id:
            for (title_key, artist_id), track in tracks_by_key.items():
                if artist_id != seed_artist_id:
                    continue
                if similarity(seed.title, title_key) >= title_min:
                    candidates.append(track)

        for track in candidates:
            candidate = build_candidate(track, seed, "title+artist")
            if candidate is None:
                continue
            if candidate.title_similarity < title_min or candidate.artist_similarity < artist_min:
                continue
            score = candidate.confidence + 0.05 * candidate.title_similarity + 0.05 * candidate.artist_similarity
            if best is None or score > best[0]:
                best = (score, candidate)

    return best[1] if best else None


def local_cleanup_candidate(
    audio: AudioInfo,
    seeds: list[Seed],
    normalize_persian: bool,
    config: Optional[dict[str, Any]] = None,
) -> Optional[Candidate]:
    if not seeds:
        return None

    config = config or DEFAULT_CONFIG
    priority = {
        "existing-tags": 0,
        "filename-title-artist": 1,
        "filename-artist-title": 2,
        "filename+default-artist": 3,
        "tag-title+default-artist": 4,
        "single-title+default-artist": 5,
    }
    seed = sorted(
        seeds,
        key=lambda item: priority.get(item.source, 99),
    )[0]

    artist = clean_artist_label(
        seed.artist,
        normalize_persian,
        config,
    )
    if not meaningful_artist_label(artist):
        return None

    album_artist = clean_artist_label(
        audio.tags.albumartist,
        normalize_persian,
        config,
    )
    album = clean_album_label(
        audio.tags.album,
        seed.title,
        normalize_persian,
        config,
    )

    final_album_artist = (
        album_artist
        if meaningful_artist_label(album_artist)
        else artist
    )

    return Candidate(
        source="local-cleanup",
        title=clean_title(seed.title, normalize_persian),
        artist=artist,
        album=album,
        album_artist=final_album_artist,
        date=audio.tags.date,
        tracknumber=audio.tags.tracknumber,
        discnumber=audio.tags.discnumber,
        genre=audio.tags.genre,
        isrc=audio.tags.isrc,
        musicbrainz_recording_id=audio.tags.musicbrainz_trackid,
        musicbrainz_release_id=audio.tags.musicbrainz_albumid,
        confidence=72.0,
        consensus_sources=["local-cleanup"],
        evidence=local_credit_evidence(
            artist,
            final_album_artist,
            normalize_persian,
            config,
        ),
    )



def unknown_fallback_candidate(
    path: Path,
    audio: AudioInfo,
    unknown_artist_folder: str,
    normalize_persian: bool,
    config: dict[str, Any],
) -> Candidate:
    raw_title = audio.tags.title or path.stem
    title = clean_title(raw_title, normalize_persian)

    parts = [
        compact_spaces(part)
        for part in title.split(" - ")
        if compact_spaces(part)
    ]
    if len(parts) >= 2:
        possible_artist = clean_artist_label(
            parts[-1],
            normalize_persian,
            config,
        )
        if not meaningful_artist_label(possible_artist):
            title = " - ".join(parts[:-1])

    title = title or "Untitled"
    display_artist = (
        unknown_artist_folder.lstrip("_ ").strip()
        or "Unknown Artist"
    )

    return Candidate(
        source="unknown-fallback",
        title=title,
        artist=display_artist,
        album=None,
        album_artist=display_artist,
        date=audio.tags.date,
        tracknumber=audio.tags.tracknumber,
        discnumber=audio.tags.discnumber,
        genre=audio.tags.genre,
        isrc=audio.tags.isrc,
        confidence=25.0,
        consensus_sources=["unknown-fallback"],
    )


def sanitize_component(
    value: str,
    normalize_persian: bool,
) -> str:
    value = normalize_text(value, normalize_persian)
    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1F]',
        " ",
        value,
    )
    value = compact_spaces(value).strip(" .")

    if not value:
        value = "Untitled"

    if value.upper() in WINDOWS_RESERVED_NAMES:
        value = f"_{value}"

    return value[:180].rstrip(" .")


def configured_worker_count(config: dict[str, Any]) -> int:
    # Mutagen parsing is partly Python-bound; on local SSDs one worker is
    # usually faster than a large thread pool. Users with slow/network disks
    # can explicitly raise this value in config.json or with --workers.
    configured = int(config.get("scan_workers", 1) or 1)
    return max(1, min(configured, 32))


def read_audio_cache_parallel(
    mp3_files: list[Path],
    config: dict[str, Any],
) -> tuple[dict[Path, AudioInfo], dict[Path, str]]:
    """Read local MP3 metadata in parallel. This is disk-I/O bound."""
    audio_cache: dict[Path, AudioInfo] = {}
    errors: dict[Path, str] = {}
    if not mp3_files:
        return audio_cache, errors

    workers = configured_worker_count(config)
    if workers == 1:
        for index, path in enumerate(mp3_files, start=1):
            try:
                audio_cache[path] = read_mp3(path)
            except Exception as exc:
                errors[path] = str(exc)
            if index % 250 == 0 or index == len(mp3_files):
                print(f"  Metadata: {index}/{len(mp3_files)}")
        return audio_cache, errors

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_path = {
            executor.submit(read_mp3, path): path
            for path in mp3_files
        }
        completed_count = 0
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                audio_cache[path] = future.result()
            except Exception as exc:
                errors[path] = str(exc)
            completed_count += 1
            if completed_count % 250 == 0 or completed_count == len(mp3_files):
                print(f"  Metadata: {completed_count}/{len(mp3_files)}")

    return audio_cache, errors


def best_musicbrainz_artist_identity(
    query_name: str,
    items: Iterable[dict[str, Any]],
    min_score: float,
) -> Optional[tuple[str, str, float, list[str]]]:
    ranked: list[tuple[float, float, str, str, list[str]]] = []
    for item in items:
        artist_id = str(item.get("id") or "")
        canonical = str(item.get("name") or "")
        if not artist_id or not canonical:
            continue

        labels = [canonical, str(item.get("sort-name") or "")]
        for alias in item.get("aliases") or []:
            if isinstance(alias, dict) and alias.get("name"):
                labels.append(str(alias["name"]))
        labels = [label for label in labels if compact_spaces(label)]

        text_score = max(
            (similarity(query_name, label) for label in labels),
            default=0.0,
        )
        provider_score = float(item.get("score") or 0.0)
        # Text/alias agreement is required. Provider rank is only a tie-breaker.
        ranked.append(
            (text_score, provider_score, artist_id, canonical, labels)
        )

    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    text_score, _, artist_id, canonical, labels = ranked[0]
    if text_score < min_score:
        return None
    return artist_id, canonical, text_score, labels


def artist_script_family(value: str) -> str:
    """Return a coarse script family for identity lookup prioritization."""
    latin = 0
    arabic = 0
    other = 0
    for char in value:
        if not char.isalpha():
            continue
        codepoint = ord(char)
        if (
            0x0041 <= codepoint <= 0x024F
            or 0x1E00 <= codepoint <= 0x1EFF
        ):
            latin += 1
        elif (
            0x0600 <= codepoint <= 0x06FF
            or 0x0750 <= codepoint <= 0x077F
            or 0x08A0 <= codepoint <= 0x08FF
            or 0xFB50 <= codepoint <= 0xFDFF
            or 0xFE70 <= codepoint <= 0xFEFF
        ):
            arabic += 1
        else:
            other += 1

    if latin and (arabic or other):
        return "mixed"
    if arabic:
        return "arabic"
    if latin:
        return "latin"
    return "other"


def _artist_identity_local_variant_keys(
    keys: list[str],
    display_names: dict[str, str],
    minimum_similarity: float,
) -> set[str]:
    """Find plausible spelling variants without doing any network requests."""
    output: set[str] = set()
    for left_index, left_key in enumerate(keys):
        left_name = display_names[left_key]
        left_family = artist_script_family(left_name)
        if left_family in {"other", "mixed"}:
            continue
        left_digits = re.findall(r"\d+", comparison_text(left_name))
        for right_key in keys[left_index + 1:]:
            right_name = display_names[right_key]
            if artist_script_family(right_name) != left_family:
                continue
            # Numeric suffixes/years often identify genuinely different artists
            # or projects. Never treat differing numbers as a spelling variant.
            if left_digits != re.findall(r"\d+", comparison_text(right_name)):
                continue
            if abs(len(comparison_text(left_name)) - len(comparison_text(right_name))) > 8:
                continue
            score = similarity(left_name, right_name)
            if minimum_similarity <= score < 100.0:
                output.add(left_key)
                output.add(right_key)
    return output


def _musicbrainz_artist_identity_search(
    client: CatalogClient,
    name: str,
    request_timeout: float,
    attempts: int,
) -> list[dict[str, Any]]:
    """Use the short identity-stage timeout when the real client supports it."""
    if isinstance(client, CatalogClient):
        return client.musicbrainz_artist_search(
            name,
            request_timeout=request_timeout,
            attempts=attempts,
        )
    # Lightweight fake clients used by tests and integrations may expose the
    # older two-argument method only.
    return client.musicbrainz_artist_search(name)


def resolve_artist_identities_online(
    plans: list[TrackPlan],
    client: CatalogClient,
    config: dict[str, Any],
    offline: bool,
) -> tuple[int, list[str]]:
    """Resolve only identities that can actually reduce folder duplication.

    v8 queried nearly every repeated artist sequentially. Because MusicBrainz
    is rate-limited, 139 artists meant a hard minimum of roughly 2.5 minutes,
    and a bad connection could make it far worse. v8.1 counts DISTINCT tracks,
    skips obvious Latin identities in smart mode, prioritizes cross-script and
    fuzzy spelling variants, propagates one provider match to all local aliases,
    and stops at a hard wall-clock budget.
    """
    if offline or not bool(config.get("resolve_artist_identities_online", True)):
        return 0, []

    mode = str(config.get("artist_identity_mode", "smart") or "smart").strip().lower()
    if mode in {"off", "disabled", "none"}:
        return 0, []
    if mode not in {"smart", "deep"}:
        mode = "smart"

    # Count each identity at most once per track. The old implementation counted
    # track artist + album artist separately, so one song could incorrectly meet
    # the minimum_tracks=2 threshold by itself.
    track_ids: dict[str, set[int]] = defaultdict(set)
    display_names: dict[str, str] = {}
    for plan_index, plan in enumerate(plans):
        seen_on_track: set[str] = set()
        for album in (False, True):
            refs = candidate_artist_refs(
                plan.candidate,
                album=album,
                normalize_persian=False,
                config=config,
            )
            for ref in refs:
                if ref.stable or is_various_artist(ref.name):
                    continue
                name_key = comparison_text(ref.name)
                if not name_key or name_key in seen_on_track:
                    continue
                seen_on_track.add(name_key)
                track_ids[name_key].add(plan_index)
                display_names.setdefault(name_key, ref.name)

    minimum_tracks = max(1, int(config.get("artist_identity_lookup_min_tracks", 2)))
    lookup_limit = max(0, int(config.get("artist_identity_lookup_limit", 30)))
    min_score = float(config.get("artist_identity_min_score", 92.0))
    variant_min_score = float(
        config.get("artist_identity_variant_min_score", 90.0)
    )
    time_budget = max(
        0.0,
        float(config.get("artist_identity_time_budget_seconds", 12.0)),
    )
    request_timeout = max(
        2.0,
        float(config.get("artist_identity_request_timeout_seconds", 5.0)),
    )
    attempts = max(
        1,
        min(3, int(config.get("artist_identity_request_attempts", 1))),
    )

    all_unstable = list(track_ids)
    repeated = [
        key
        for key, paths in track_ids.items()
        if len(paths) >= minimum_tracks
    ]
    repeated.sort(
        key=lambda key: (-len(track_ids[key]), comparison_text(display_names[key]))
    )

    if not all_unstable:
        print("  Artist identities: no unresolved identities; skipped.")
        return 0, []

    if mode == "deep":
        selected = list(repeated)
    else:
        # Smart mode may still inspect a one-track non-Latin spelling because it
        # can be the exact alias that created a duplicate folder. Latin one-offs
        # remain skipped. Fuzzy same-script variants are also candidates when
        # at least one side has meaningful library support.
        variant_keys = _artist_identity_local_variant_keys(
            all_unstable,
            display_names,
            variant_min_score,
        )
        supported_variant_keys = {
            key
            for key in variant_keys
            if len(track_ids[key]) >= minimum_tracks
            or any(
                other != key
                and other in variant_keys
                and len(track_ids[other]) >= minimum_tracks
                and similarity(display_names[key], display_names[other]) >= variant_min_score
                for other in variant_keys
            )
        }
        has_latin_identity = any(
            artist_script_family(display_names[key]) == "latin"
            for key in all_unstable
        )
        selected = [
            key
            for key in all_unstable
            if (
                key in supported_variant_keys
                or (
                    has_latin_identity
                    and artist_script_family(display_names[key]) in {"arabic", "mixed"}
                )
            )
        ]
        selected.sort(
            key=lambda key: (
                0 if key in supported_variant_keys else 1,
                0 if artist_script_family(display_names[key]) in {"arabic", "mixed"} else 1,
                -len(track_ids[key]),
                comparison_text(display_names[key]),
            )
        )

    if lookup_limit:
        selected = selected[:lookup_limit]

    if not selected:
        print(
            f"  Artist identities: smart mode skipped all {len(all_unstable)} "
            "clear identities (no useful alias lookup needed)."
        )
        return 0, []

    budget_text = "unlimited" if time_budget <= 0 else f"{time_budget:.0f}s max"
    print(
        f"  Artist identities: {mode} mode selected {len(selected)} of "
        f"{len(all_unstable)} unresolved identities ({budget_text})."
    )

    # mapping value: (stable key, canonical name, confidence)
    mapping: dict[str, tuple[str, str, float]] = {}
    errors: list[str] = []
    started = time.monotonic()
    network_queries = 0
    processed = 0
    budget_reached = False

    all_local_keys = list(display_names)
    for name_key in selected:
        processed += 1
        # A previous lookup can resolve several aliases at once. Do not query a
        # second spelling/script after it has already been mapped.
        if name_key in mapping:
            continue

        if time_budget > 0 and time.monotonic() - started >= time_budget:
            budget_reached = True
            break

        name = display_names[name_key]
        try:
            items = _musicbrainz_artist_identity_search(
                client,
                name,
                request_timeout,
                attempts,
            )
            network_queries += 1
            match = best_musicbrainz_artist_identity(name, items, min_score)
            if match is not None:
                artist_id, canonical, query_score, labels = match
                stable_key = f"mb:{artist_id}"
                candidate_labels = list(dict.fromkeys([canonical, *labels]))

                # Always map the queried name.
                mapping[name_key] = (stable_key, canonical, query_score)

                # One MusicBrainz result often contains aliases in several
                # scripts. Propagate that identity to every matching local name,
                # which avoids another one-second MusicBrainz request per alias.
                for local_key in all_local_keys:
                    local_name = display_names[local_key]
                    local_score = max(
                        (
                            similarity(local_name, label)
                            for label in candidate_labels
                            if label
                        ),
                        default=0.0,
                    )
                    if local_score < min_score:
                        continue
                    current = mapping.get(local_key)
                    if current is None or local_score > current[2]:
                        mapping[local_key] = (
                            stable_key,
                            canonical,
                            local_score,
                        )
        except Exception as exc:
            errors.append(f"Artist identity {name}: {exc}")

        if processed % 5 == 0 or processed == len(selected):
            elapsed = time.monotonic() - started
            print(
                f"  Artist identities: {processed}/{len(selected)} candidates, "
                f"{network_queries} lookups, {elapsed:.1f}s"
            )

    elapsed = time.monotonic() - started
    if budget_reached:
        print(
            f"  Artist identities: time budget reached after {elapsed:.1f}s; "
            "continuing with local evidence for the remaining artists."
        )

    if not mapping:
        return 0, errors

    resolved = 0
    for plan in plans:
        candidate = plan.candidate
        for prefix in ("track_artist", "album_artist"):
            names = candidate.evidence.get(f"{prefix}_entities")
            if not isinstance(names, list) or not names:
                continue
            raw_keys = candidate.evidence.get(f"{prefix}_keys")
            keys = list(raw_keys) if isinstance(raw_keys, list) else [""] * len(names)
            while len(keys) < len(names):
                keys.append("")

            changed = False
            for idx, raw_name in enumerate(names):
                current_key = str(keys[idx] or "")
                if current_key and not current_key.startswith("name:"):
                    continue
                match = mapping.get(comparison_text(str(raw_name)))
                if match is None:
                    continue
                keys[idx] = match[0]
                if bool(config.get("prefer_provider_canonical_artist_name", True)):
                    names[idx] = match[1]
                changed = True
                resolved += 1
            if changed:
                candidate.evidence[f"{prefix}_keys"] = keys
                candidate.evidence[f"{prefix}_entities"] = names

    return resolved, errors

def refs_equivalent(left: ArtistRef, right: ArtistRef) -> bool:
    if left.key and right.key and left.key == right.key:
        return True
    return similarity(left.name, right.name) >= 94


def matching_ref(refs: list[ArtistRef], name: Optional[str]) -> Optional[ArtistRef]:
    if not name:
        return None
    ranked = [
        (similarity(ref.name, name), ref)
        for ref in refs
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked[0][0] >= 90 else None


def composite_identity_candidates(
    raw_ref: ArtistRef,
    profile: LibraryProfile,
) -> list[ArtistRef]:
    """Find strong known identities embedded in a malformed combined label.

    This handles generic cases where a tag concatenates two performers without
    a separator. A single substring match is not enough; we only trust either
    two strong known identities or one identity plus a brand-like remainder.
    """
    raw_text = comparison_text(raw_ref.name)
    if not raw_text:
        return []

    strong: list[ArtistRef] = []
    for key, variants in profile.entity_variants.items():
        if key == raw_ref.key or not variants:
            continue
        name = variants.most_common(1)[0][0]
        ref = ArtistRef(name, key, not key.startswith("name:"))
        if profile.entity_authority(ref) < 12.0:
            continue
        known = comparison_text(name)
        if not known or known == raw_text:
            continue
        if re.search(rf"(?:^|\s){re.escape(known)}(?:$|\s)", raw_text):
            strong.append(ref)

    strong = dedupe_artist_refs(strong)
    if len(strong) >= 2:
        return strong

    if len(strong) == 1:
        known_name = strong[0].name
        raw_lower = raw_ref.name.casefold()
        known_lower = known_name.casefold()
        remainder = ""
        if raw_lower.startswith(known_lower):
            remainder = raw_ref.name[len(known_name):].strip(" -_/&,+")
        elif raw_lower.endswith(known_lower):
            remainder = raw_ref.name[:-len(known_name)].strip(" -_/&,+")
        if remainder and looks_like_source_brand(remainder):
            return strong

    return []


def resolve_primary_artist_ref(
    candidate: Candidate,
    old_tags: Tags,
    profile: LibraryProfile,
    normalize_persian: bool,
    config: dict[str, Any],
) -> Optional[ArtistRef]:
    """Choose one folder identity while preserving full track credits.

    The resolver is intentionally generic. It does not know any real artist
    names. It combines provider structure, album ownership, explicit feature
    syntax, existing performer tags, composer/lyricist exclusions, and
    library-wide behavior.
    """
    track_refs = candidate_artist_refs(
        candidate,
        album=False,
        normalize_persian=normalize_persian,
        config=config,
    )
    album_refs = candidate_artist_refs(
        candidate,
        album=True,
        normalize_persian=normalize_persian,
        config=config,
    )

    if not track_refs:
        track_refs = album_refs
    if not track_refs:
        return None

    role_names = role_tag_names(old_tags, normalize_persian, config)
    old_refs = text_artist_refs(old_tags.artist, normalize_persian, config)
    old_single = old_refs[0] if len(old_refs) == 1 else None

    # Never let an explicitly tagged composer/lyricist replace a different
    # plausible local singer. Singer/track performer wins; instrumental artist
    # is considered only when no vocal performer can be established.
    if (
        len(track_refs) == 1
        and bool(config.get("artist_role_intelligence", True))
        and comparison_text(track_refs[0].name) in role_names
        and old_single is not None
        and comparison_text(old_single.name) not in role_names
        and not refs_equivalent(track_refs[0], old_single)
    ):
        candidate.evidence["folder_identity_reason"] = "local-performer-over-composer-lyricist"
        return old_single

    atomic = bool(candidate.evidence.get("track_artist_atomic"))
    provider_atomic = bool(
        candidate.source in {"musicbrainz", "spotify", "apple", "consensus", "acoustid"}
        and atomic
    )
    if len(track_refs) == 1 and (track_refs[0].stable or provider_atomic):
        candidate.evidence["folder_identity_reason"] = (
            "stable-provider-identity" if track_refs[0].stable else "provider-atomic-identity"
        )
        return track_refs[0]

    if len(track_refs) == 1 and bool(config.get("artist_role_intelligence", True)):
        embedded = composite_identity_candidates(track_refs[0], profile)
        if embedded:
            track_refs = embedded
            candidate.evidence["folder_identity_composite_recovered"] = True

    # Explicit "A feat. B" is the strongest syntax-level primary signal.
    explicit_primary = explicit_feature_primary_name(
        candidate.artist,
        normalize_persian,
        config,
    )
    explicit_ref = matching_ref(track_refs, explicit_primary)

    old_supported = (
        matching_ref(track_refs, old_single.name)
        if old_single is not None
        else None
    )

    album_anchor: Optional[ArtistRef] = None
    if len(album_refs) == 1 and not is_various_artist(album_refs[0].name):
        for ref in track_refs:
            if refs_equivalent(ref, album_refs[0]):
                album_anchor = ref
                break

    non_role_exists = any(
        comparison_text(ref.name) not in role_names
        for ref in track_refs
    )

    ranked: list[tuple[float, int, ArtistRef]] = []
    for index, ref in enumerate(track_refs):
        score = profile.entity_authority(ref)

        # Provider order is a useful tie-breaker, not the whole decision.
        score += 8.0 if index == 0 else max(0.0, 3.0 - index)
        if ref.stable:
            score += 4.0
        if explicit_ref is not None and refs_equivalent(ref, explicit_ref):
            score += 30.0
        if album_anchor is not None and refs_equivalent(ref, album_anchor):
            score += 24.0
        if (
            bool(config.get("prefer_supported_existing_artist", True))
            and old_supported is not None
            and refs_equivalent(ref, old_supported)
        ):
            score += 18.0

        # A name explicitly tagged as composer/lyricist should not own the
        # artist folder when another plausible performer exists.
        if (
            bool(config.get("artist_role_intelligence", True))
            and non_role_exists
            and comparison_text(ref.name) in role_names
        ):
            score -= 45.0

        # Identities that only appear as secondary credits are weak folder
        # owners compared with identities that have solo/album evidence.
        if (
            profile.entity_solo_counts[ref.key] == 0
            and profile.entity_album_anchor_counts[ref.key] == 0
            and profile.entity_secondary_counts[ref.key] > 0
        ):
            score -= 8.0

        ranked.append((score, -index, ref))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = ranked[0][2]
    reasons: list[str] = []
    if explicit_ref is not None and refs_equivalent(chosen, explicit_ref):
        reasons.append("explicit-feature-primary")
    if album_anchor is not None and refs_equivalent(chosen, album_anchor):
        reasons.append("album-owner")
    if old_supported is not None and refs_equivalent(chosen, old_supported):
        reasons.append("supported-existing-performer")
    if candidate.evidence.get("folder_identity_composite_recovered"):
        reasons.append("composite-credit-recovery")
    if (
        bool(config.get("artist_role_intelligence", True))
        and not bool(config.get("allow_non_vocal_artist_folders", False))
        and ref_is_non_vocal_registry_only(chosen, config)
    ):
        for score, _, ref in ranked:
            if not ref_is_non_vocal_registry_only(ref, config):
                chosen = ref
                reasons.append("non-vocal-registry-demoted")
                break
        else:
            candidate.evidence["folder_identity_reason"] = "non-vocal-registry-review"
            candidate.evidence["folder_identity_scores"] = [
                {"artist": ref.name, "score": round(score, 2)}
                for score, _, ref in ranked[:6]
            ]
            return None

    if not reasons:
        reasons.append("library-role-authority")
    candidate.evidence["folder_identity_reason"] = ",".join(reasons)
    candidate.evidence["folder_identity_scores"] = [
        {"artist": ref.name, "score": round(score, 2)}
        for score, _, ref in ranked[:6]
    ]
    return chosen


def build_profile_from_plans(
    plans: list[TrackPlan],
    normalize_persian: bool,
    config: dict[str, Any],
) -> LibraryProfile:
    """Build identity statistics from identified candidates in two passes."""
    profile = LibraryProfile(config)

    # Pass A: learn which identities behave like solo performers, album owners,
    # leads, or secondary contributors. Multi-credit strings are never added as
    # a single folder identity unless the provider explicitly made them atomic.
    for plan in plans:
        candidate = plan.candidate
        track_refs = candidate_artist_refs(
            candidate,
            album=False,
            normalize_persian=normalize_persian,
            config=config,
        )
        album_refs = candidate_artist_refs(
            candidate,
            album=True,
            normalize_persian=normalize_persian,
            config=config,
        )
        profile.register_track(track_refs, album_refs)

        # Existing single-artist tags are weak alias evidence when the provider
        # also supports that identity. This helps preserve a user's canonical
        # spelling without allowing stale composer/collaboration tags to create
        # extra folders.
        old_refs = text_artist_refs(
            plan.audio.tags.artist,
            normalize_persian,
            config,
        )
        if len(old_refs) == 1 and matching_ref(track_refs, old_refs[0].name):
            supported = matching_ref(track_refs, old_refs[0].name)
            if supported is not None:
                profile.entity_variants[supported.key][old_refs[0].name] += 1
                profile.name_to_entity_keys[comparison_text(old_refs[0].name)][supported.key] += 1

    # Pass B: once role statistics exist, learn album spelling under the final
    # coarse folder identity.
    for plan in plans:
        candidate = plan.candidate
        album = clean_album_label(
            candidate.album or plan.audio.tags.album,
            candidate.title,
            normalize_persian,
            config,
        )
        primary = resolve_primary_artist_ref(
            candidate,
            plan.audio.tags,
            profile,
            normalize_persian,
            config,
        )
        if primary is None:
            continue
        canonical = profile.canonical_artist(primary.name, primary.key)
        if album:
            profile.add_album(canonical, album)

    return profile


def build_library_profile(
    mp3_files: list[Path],
    normalize_persian: bool,
    config: dict[str, Any],
) -> tuple[LibraryProfile, dict[Path, AudioInfo]]:
    profile = LibraryProfile(config)
    audio_cache: dict[Path, AudioInfo] = {}

    for path in mp3_files:
        audio = read_mp3(path)
        audio_cache[path] = audio

        title = clean_title(
            audio.tags.title or path.stem,
            normalize_persian,
        )
        album = clean_album_label(
            audio.tags.album,
            title,
            normalize_persian,
            config,
        )

        labels: list[str] = []
        for raw in (
            audio.tags.albumartist,
            audio.tags.artist,
        ):
            cleaned = clean_artist_label(
                raw,
                normalize_persian,
                config,
            )
            if meaningful_artist_label(cleaned):
                labels.append(cleaned)

        if not labels:
            seeds = generate_seeds(
                path,
                audio.tags,
                None,
                normalize_persian,
                config,
            )
            if seeds:
                labels.append(seeds[0].artist)

        for label in dict.fromkeys(labels):
            profile.add_artist(label, album)

            primary = first_primary_artist(label)
            if meaningful_artist_label(primary):
                profile.add_artist(primary, album)

            if album:
                profile.add_album(label, album)
                if meaningful_artist_label(primary):
                    profile.add_album(primary, album)

    return profile, audio_cache


def primary_artist_for_folder(
    candidate: Candidate,
    old_tags: Tags,
    profile: LibraryProfile,
    unknown_artist_folder: str,
    normalize_persian: bool,
    config: dict[str, Any],
    album_label: Optional[str],
) -> str:
    if (
        str(config.get("folder_granularity", "primary_identity")) == "joint_credit"
        and bool(config.get("allow_joint_artist_folders", False))
    ):
        joint = clean_artist_label(candidate.artist, normalize_persian, config)
        if (
            meaningful_artist_label(joint)
            and has_collaboration_separator(joint)
            and profile.should_preserve_collaboration(joint, album_label, config)
        ):
            return format_artist_folder_name(
                profile.canonical_artist(joint),
                normalize_persian,
                config,
            )

    primary = resolve_primary_artist_ref(
        candidate,
        old_tags,
        profile,
        normalize_persian,
        config,
    )

    if primary is None:
        if candidate.evidence.get("folder_identity_reason") == "non-vocal-registry-review":
            return sanitize_component(
                str(config.get("non_vocal_review_folder", "Review - Non Vocal Artists")),
                normalize_persian,
            )
        return sanitize_component(unknown_artist_folder, normalize_persian)

    artist = profile.canonical_artist(primary.name, primary.key)
    artist = clean_artist_label(artist, normalize_persian, config)
    if not meaningful_artist_label(artist):
        return sanitize_component(unknown_artist_folder, normalize_persian)

    return format_artist_folder_name(artist, normalize_persian, config)


def format_artist_folder_name(
    artist: str,
    normalize_persian: bool,
    config: dict[str, Any],
) -> str:
    """Format only real Artist folders; system folders keep their configured names."""
    value = sanitize_component(artist, normalize_persian)
    style = str(config.get("artist_folder_name_style", "display") or "display").strip().lower()
    if style in {"snake", "snake_case", "underscore"}:
        value = re.sub(r"[^\w]+", "_", value, flags=re.UNICODE).strip("_")
        value = re.sub(r"_+", "_", value)
        value = value.casefold()
    else:
        # Downloader labels often arrive as alireza_ghorbani or all lowercase.
        # Keep Persian/non-Latin text untouched, but make Latin folder names
        # human-readable: Alireza Ghorbani.
        value = re.sub(r"_+", " ", value)
        if re.fullmatch(r"[A-Za-z0-9 .&'’\-]+", value) and not any(
            char.isupper() for char in value
        ):
            value = value.title()
        value = compact_spaces(value)
    return value or "untitled"



def singles_folder_name(config: dict[str, Any], normalize_persian: bool) -> str:
    return sanitize_component(str(config.get("singles_folder", "Singles")), normalize_persian)


def is_singles_folder(album_folder: Optional[str], config: dict[str, Any]) -> bool:
    if not album_folder:
        return True
    return comparison_text(str(album_folder)) == comparison_text(str(config.get("singles_folder", "Singles")))


def strip_single_release_words(value: str) -> str:
    key = comparison_text(value)
    key = re.sub(r"\b(?:single|singles|ep|radio edit|remix|remastered|original mix)\b", " ", key)
    return compact_spaces(key)


def album_title_similarity(album: str, title: Optional[str]) -> float:
    if not album or not title:
        return 0.0
    return float(fuzz.WRatio(strip_single_release_words(album), strip_single_release_words(title)))


def release_track_total(candidate: Candidate, old_tags: Tags) -> Optional[int]:
    for value in (
        candidate.evidence.get("release_track_count"),
        candidate.evidence.get("track_count"),
    ):
        try:
            if value is not None:
                total = int(value)
                if total > 0:
                    return total
        except (TypeError, ValueError):
            pass

    for raw in (candidate.tracknumber, old_tags.tracknumber):
        if not raw:
            continue
        match = re.search(r"(?:/|of\s+)(\d{1,3})\b", str(raw), flags=re.IGNORECASE)
        if match:
            try:
                total = int(match.group(1))
                if total > 0:
                    return total
            except ValueError:
                pass
    return None


def release_primary_type(candidate: Candidate) -> str:
    return str(candidate.evidence.get("release_primary_type") or "").casefold().strip()


def album_looks_like_single_release(album: str, title: Optional[str], config: dict[str, Any]) -> bool:
    key = comparison_text(album)
    if not key:
        return True
    single_markers = {
        "single", "singles", "radio edit", "remix", "original mix"
    }
    if key in single_markers:
        return True
    if " single " in f" {key} " or key.endswith(" single"):
        return True
    # EP can be a real release; do not collapse every EP only because of the
    # word. A one-track EP will still be collapsed by the trust gate below.
    threshold = float(config.get("album_title_similarity_single_threshold", 88.0))
    return bool(title and album_title_similarity(album, title) >= threshold)


def album_is_trusted_for_folder(
    album: str,
    candidate: Candidate,
    old_tags: Tags,
    album_track_count_in_library: int,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Decide whether an album label may create a subfolder.

    Reliability rule: it is safer to put a doubtful one-track release into
    Artist/Singles than to create a fake folder named after every song.  This
    fixes Persian catalogs where providers often expose singles as releases.
    """
    if not bool(config.get("album_trust_gate_enabled", True)):
        return True, "gate-disabled"

    if is_singles_folder(album, config):
        return False, "singles-folder"

    min_tracks = int(config.get("album_folder_min_tracks", 2) or 2)
    album_count = max(0, int(album_track_count_in_library or 0))
    source = str(candidate.source or "").casefold()
    primary_type = release_primary_type(candidate)
    total_tracks = release_track_total(candidate, old_tags)
    title_like_single = album_looks_like_single_release(album, candidate.title, config)

    if album_count >= min_tracks:
        return True, f"library-multi-track:{album_count}"

    if total_tracks is not None and total_tracks >= min_tracks:
        return True, f"release-track-count:{total_tracks}"

    if primary_type == "single":
        return False, "provider-release-type-single"

    if title_like_single:
        return False, "album-title-matches-track-title"

    if primary_type == "album" and bool(config.get("trust_single_track_musicbrainz_album", True)) and source in {"musicbrainz", "acoustid"}:
        return True, "trusted-open-provider-album"

    if primary_type == "album" and source == "spotify":
        return False, "spotify-single-track-album-not-trusted"

    if source == "local-registry" and bool(config.get("trust_single_track_local_registry_album", True)):
        return True, "trusted-local-registry-album"

    # Existing tags and weak catalog results need library evidence. Otherwise
    # one-track album labels are treated as singles to avoid ChaarTaar/Dang Show
    # style one-folder-per-song mistakes.
    return False, "not-enough-album-evidence"


def reliable_album_folder_for(
    raw_album_folder: str,
    candidate: Candidate,
    old_tags: Tags,
    album_track_count_in_library: int,
    normalize_persian: bool,
    config: dict[str, Any],
) -> str:
    singles = singles_folder_name(config, normalize_persian)
    if not raw_album_folder or is_singles_folder(raw_album_folder, config):
        candidate.evidence["album_folder_reason"] = "singles-or-empty"
        return singles

    trusted, reason = album_is_trusted_for_folder(
        raw_album_folder,
        candidate,
        old_tags,
        album_track_count_in_library,
        config,
    )
    candidate.evidence["album_folder_reason"] = reason
    if trusted:
        return raw_album_folder
    return singles


def album_folder_for(
    candidate: Candidate,
    old_tags: Tags,
    artist_folder: str,
    profile: LibraryProfile,
    normalize_persian: bool,
    config: dict[str, Any],
) -> str:
    album = clean_album_label(
        candidate.album or old_tags.album,
        candidate.title,
        normalize_persian,
        config,
    )

    if not album:
        return sanitize_component(
            str(config.get("singles_folder", "Singles")),
            normalize_persian,
        )

    album = profile.canonical_album(artist_folder, album)
    return sanitize_component(album, normalize_persian)


def destination_album_folder(
    album_folder: str,
    config: dict[str, Any],
) -> str:
    """Return the Album/_Singles subfolder below the canonical Artist folder.

    The explicit ``album_subfolders_enabled`` option controls the layout.
    ``artist_subfolders_enabled`` is accepted only as a legacy fallback for
    older configuration files.
    """
    if "album_subfolders_enabled" in config:
        enabled = bool(config.get("album_subfolders_enabled", True))
    else:
        enabled = bool(config.get("artist_subfolders_enabled", True))
    return album_folder if enabled else ""


def output_artist_credit(
    candidate: Candidate,
    old_tags: Tags,
    profile: LibraryProfile,
    normalize_persian: bool,
    config: dict[str, Any],
) -> str:
    """Build a deterministic filename credit: Primary (Guest A x Guest B).

    Folder ownership and filename credits use the same resolved primary identity,
    preventing a collaboration from creating another Artist folder while still
    preserving every credited performer in the filename.
    """
    refs = candidate_artist_refs(
        candidate,
        album=False,
        normalize_persian=normalize_persian,
        config=config,
    )
    primary = resolve_primary_artist_ref(
        candidate,
        old_tags,
        profile,
        normalize_persian,
        config,
    )

    if primary is None:
        fallback = clean_artist_label(candidate.artist, normalize_persian, config)
        return fallback or "Unknown Artist"

    primary_name = clean_artist_label(
        profile.canonical_artist(primary.name, primary.key),
        normalize_persian,
        config,
    ) or primary.name

    guests: list[str] = []
    seen = {comparison_text(primary_name)}
    for ref in refs:
        if refs_equivalent(ref, primary):
            continue
        guest = clean_artist_label(
            profile.canonical_artist(ref.name, ref.key),
            normalize_persian,
            config,
        ) or ref.name
        marker = comparison_text(guest)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        guests.append(guest)

    style = str(
        config.get(
            "filename_artist_credit_style",
            "primary_with_guests_parentheses",
        )
        or "primary_with_guests_parentheses"
    ).strip().lower()
    if not guests or style in {"primary_only", "primary"}:
        return primary_name
    if style in {"provider_credit", "original"}:
        original = clean_artist_label(candidate.artist, normalize_persian, config)
        return original or primary_name

    separator = str(config.get("filename_guest_separator", " x ") or " x ")
    separator = compact_spaces(separator)
    if not separator:
        separator = " x "
    else:
        separator = f" {separator.strip()} "
    return f"{primary_name} ({separator.join(guests)})"


def build_filename(
    title: str,
    artist: str,
    normalize_persian: bool,
) -> str:
    clean_name = sanitize_component(
        clean_title(title, normalize_persian),
        normalize_persian,
    )
    clean_artist = sanitize_component(
        clean_title(artist, normalize_persian),
        normalize_persian,
    )
    return f"{clean_name} - {clean_artist}.mp3"


def truncate_name(value: str, max_length: int) -> str:
    value = value.rstrip(" .")
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip(" .")


def fit_target_path(
    output_root: Path,
    artist_folder: str,
    album_folder: str,
    filename: str,
    max_path_length: int,
) -> tuple[str, str, str, Path]:
    """Shorten destination components until the Windows path budget fits.

    ``album_folder`` may be an empty string when ``album_subfolders_enabled``
    is disabled. In that flat layout the target is ``Artist / Song.mp3``.
    """
    max_path_length = max(160, int(max_path_length or 240))
    artist = artist_folder
    album = album_folder
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".mp3"

    def build() -> Path:
        if album:
            return output_root / artist / album / f"{stem}{suffix}"
        return output_root / artist / f"{stem}{suffix}"

    minimums = {"artist": 20, "album": 20, "stem": 48}
    for _ in range(16):
        target = build()
        overflow = len(str(target)) - max_path_length
        if overflow <= 0:
            return artist, album, f"{stem}{suffix}", target

        lengths = {
            "artist": len(artist) - minimums["artist"],
            "album": len(album) - minimums["album"],
            "stem": len(stem) - minimums["stem"],
        }
        key = max(lengths, key=lengths.get)
        if lengths[key] <= 0:
            break
        cut = min(overflow, max(1, lengths[key]))
        if key == "artist":
            artist = truncate_name(artist, len(artist) - cut)
        elif key == "album":
            album = truncate_name(album, len(album) - cut)
        else:
            stem = truncate_name(stem, len(stem) - cut)

    target = build()
    if len(str(target)) > max_path_length:
        raise RuntimeError(
            "The output root is too long for the configured max_path_length. "
            "Choose a shorter output path or increase max_path_length."
        )
    return artist, album, f"{stem}{suffix}", target


def same_path(left: Path, right: Path) -> bool:
    return (
        os.path.normcase(os.path.abspath(left))
        == os.path.normcase(os.path.abspath(right))
    )


def path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_rename(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    if source == target:
        return

    if same_path(source, target):
        temporary = source.with_name(
            f".__smart_music_tmp_{uuid.uuid4().hex}{source.suffix}"
        )
        source.rename(temporary)
        temporary.rename(target)
    else:
        source.rename(target)


def set_easy_tag(
    audio: Any,
    key: str,
    value: Optional[str | list[str]],
) -> None:
    if value is None or value == "":
        return

    values = value if isinstance(value, list) else [str(value)]
    try:
        audio[key] = values
    except (KeyError, ValueError):
        pass


def write_bitrate_id3_tags(
    path: Path,
    bitrate_bps: Optional[int],
    bitrate_mode: Optional[str],
    id3_version: str,
) -> None:
    if not bitrate_bps:
        return

    bitrate_kbps = int(round(bitrate_bps / 1000))
    tags = ID3(path)

    tags.delall("TXXX:BITRATE")
    tags.delall("TXXX:BITRATE_MODE")

    encoding = 1 if id3_version == "2.3" else 3
    tags.add(
        TXXX(
            encoding=encoding,
            desc="BITRATE",
            text=[f"{bitrate_kbps} kbps"],
        )
    )

    if bitrate_mode:
        tags.add(
            TXXX(
                encoding=encoding,
                desc="BITRATE_MODE",
                text=[bitrate_mode],
            )
        )

    tags.save(v2_version=3 if id3_version == "2.3" else 4)


def write_tags(
    path: Path,
    candidate: Candidate,
    old_tags: Tags,
    audio_info: AudioInfo,
    id3_version: str,
    write_bitrate_tag: bool,
) -> None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise RuntimeError("Mutagen cannot edit this MP3 file.")

    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:
            pass

    set_easy_tag(
        audio,
        "title",
        clean_title(candidate.title, False),
    )
    set_easy_tag(audio, "artist", candidate.artist)
    set_easy_tag(
        audio,
        "albumartist",
        candidate.album_artist or candidate.artist,
    )
    if candidate.album:
        set_easy_tag(
            audio,
            "album",
            candidate.album,
        )
    else:
        try:
            del audio["album"]
        except Exception:
            pass
    set_easy_tag(
        audio,
        "date",
        candidate.date or old_tags.date,
    )
    set_easy_tag(
        audio,
        "tracknumber",
        candidate.tracknumber or old_tags.tracknumber,
    )
    set_easy_tag(
        audio,
        "discnumber",
        candidate.discnumber or old_tags.discnumber,
    )
    set_easy_tag(
        audio,
        "genre",
        candidate.genre or old_tags.genre,
    )
    set_easy_tag(
        audio,
        "isrc",
        candidate.isrc or old_tags.isrc,
    )
    set_easy_tag(
        audio,
        "musicbrainz_trackid",
        candidate.musicbrainz_recording_id,
    )
    set_easy_tag(
        audio,
        "musicbrainz_artistid",
        candidate.musicbrainz_artist_ids,
    )
    set_easy_tag(
        audio,
        "musicbrainz_albumid",
        candidate.musicbrainz_release_id,
    )

    audio.save(v2_version=3 if id3_version == "2.3" else 4)

    if write_bitrate_tag:
        write_bitrate_id3_tags(
            path,
            audio_info.bitrate_bps,
            audio_info.bitrate_mode,
            id3_version,
        )


def restore_tags(
    path: Path,
    old_tags: dict[str, Any],
    id3_version: str,
) -> None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise RuntimeError("Mutagen cannot restore this MP3 file.")

    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception:
            pass

    keys = (
        "title",
        "artist",
        "albumartist",
        "album",
        "date",
        "tracknumber",
        "discnumber",
        "genre",
        "isrc",
        "musicbrainz_trackid",
        "musicbrainz_artistid",
        "musicbrainz_albumid",
    )

    for key in keys:
        value = old_tags.get(key)
        if value:
            set_easy_tag(audio, key, value)
        else:
            try:
                del audio[key]
            except Exception:
                pass

    audio.save(v2_version=3 if id3_version == "2.3" else 4)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class AppRunLock:
    """Prevent two organizer instances from mutating the same app journal state."""

    def __init__(self, app_dir: Path) -> None:
        self.path = app_dir / "organizer.lock"
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        },
                        handle,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                self.acquired = True
                return True
            except FileExistsError:
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(payload.get("pid") or 0)
                except Exception:
                    pid = 0
                if process_is_alive(pid):
                    return False
                try:
                    self.path.unlink()
                except OSError:
                    return False
        return False

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self.acquired = False


class RunJournal:
    """Append-only crash journal plus compact final undo manifest."""

    def __init__(
        self,
        run_dir: Path,
        app_dir: Path,
        metadata: dict[str, Any],
        fsync: bool = True,
    ) -> None:
        self.run_dir = run_dir
        self.app_dir = app_dir
        self.metadata = dict(metadata)
        self.fsync = fsync
        self.journal_path = run_dir / "journal.jsonl"
        self.manifest_path = run_dir / "changes.json"
        self.active_path = app_dir / "active_run.json"
        self.changes: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.active_path,
            {
                "run_dir": str(self.run_dir),
                "journal": str(self.journal_path),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._append({"event": "run_start", "metadata": self.metadata})

    def _append(self, event: dict[str, Any]) -> None:
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())

    def begin(self, change: dict[str, Any]) -> dict[str, Any]:
        current = dict(change)
        current.setdefault("id", uuid.uuid4().hex)
        current["status"] = "pending"
        change_id = current["id"]
        self.changes[change_id] = current
        if change_id not in self.order:
            self.order.append(change_id)
        self._append({"event": "begin", "change": current})
        return current

    def finish(self, change: dict[str, Any]) -> None:
        change_id = str(change["id"])
        current = dict(change)
        self.changes[change_id] = current
        if change_id not in self.order:
            self.order.append(change_id)
        self._append({"event": "finish", "change": current})

    def compact_manifest(self, status: str, extra: Optional[dict[str, Any]] = None) -> None:
        payload = dict(self.metadata)
        payload.update(extra or {})
        payload["status"] = status
        payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        payload["changes"] = [self.changes[item] for item in self.order]
        atomic_write_json(self.manifest_path, payload)

    def close(self, status: str = "completed", extra: Optional[dict[str, Any]] = None) -> None:
        self.compact_manifest(status, extra)
        self._append({"event": "run_end", "status": status})
        try:
            self.active_path.unlink(missing_ok=True)
        except OSError:
            pass


def load_journal_state(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    metadata: dict[str, Any] = {}
    changes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    ended = False
    if not path.exists():
        return metadata, [], ended

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        kind = event.get("event")
        if kind == "run_start":
            metadata = dict(event.get("metadata") or {})
        elif kind in {"begin", "finish"}:
            change = dict(event.get("change") or {})
            change_id = str(change.get("id") or "")
            if not change_id:
                continue
            changes[change_id] = change
            if change_id not in order:
                order.append(change_id)
        elif kind == "run_end":
            ended = True

    return metadata, [changes[item] for item in order], ended


def snapshot_id3(path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        backup_path.write_bytes(b"")
        return
    tags.save(backup_path, v2_version=4)


def restore_id3_snapshot(
    path: Path,
    backup_path: Path,
    id3_version: str,
) -> None:
    # Remove every ID3v2 frame first, including custom TXXX/APIC frames.
    ID3().delete(path, delete_v1=False, delete_v2=True)
    if backup_path.exists() and backup_path.stat().st_size > 0:
        tags = ID3(backup_path)
        tags.save(path, v2_version=3 if id3_version == "2.3" else 4)


def rollback_pending_change(change: dict[str, Any], id3_version: str) -> tuple[bool, str]:
    mode = change.get("mode")
    source = Path(str(change.get("source") or ""))
    final = Path(str(change.get("final") or ""))
    staging_value = str(change.get("staging") or "")
    staging = Path(staging_value) if staging_value else None

    try:
        if mode == "copy":
            if staging and staging.exists():
                staging.unlink()
            if final.exists() and source.exists() and not same_path(final, source):
                final.unlink()
            return True, "copy rollback complete"

        holder: Optional[Path] = None
        if staging and staging.exists():
            holder = staging
        elif final.exists() and not source.exists():
            holder = final
        elif source.exists():
            holder = source

        if holder is None:
            return False, "No recoverable file was found."

        snapshot_value = str(change.get("tag_snapshot") or "")
        if (
            change.get("kind") == "mp3"
            and snapshot_value
            and Path(snapshot_value).exists()
        ):
            restore_id3_snapshot(holder, Path(snapshot_value), id3_version)

        if not same_path(holder, source):
            if source.exists():
                return False, f"Original path is occupied: {source}"
            source.parent.mkdir(parents=True, exist_ok=True)
            safe_rename(holder, source)

        return True, f"restored {source}"
    except Exception as exc:
        return False, str(exc)


def recover_active_run(app_dir: Path) -> None:
    active_path = app_dir / "active_run.json"
    if not active_path.exists():
        return

    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        journal_path = Path(active["journal"])
        metadata, changes, ended = load_journal_state(journal_path)
        if ended:
            active_path.unlink(missing_ok=True)
            return

        print("Recovering an interrupted previous run...")
        id3_version = str(metadata.get("id3_version", "2.3"))
        failures = 0
        for change in reversed(changes):
            if change.get("status") != "pending":
                continue
            ok, message = rollback_pending_change(change, id3_version)
            change["status"] = "recovered-rollback" if ok else "recovery-error"
            change["error"] = None if ok else message
            print(("  RECOVERED: " if ok else "  RECOVERY ERROR: ") + message)
            failures += 0 if ok else 1

        recovered_manifest = dict(metadata)
        recovered_manifest.update({
            "status": "recovered" if failures == 0 else "recovery-errors",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "changes": changes,
        })
        atomic_write_json(journal_path.parent / "changes.json", recovered_manifest)

        with journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "event": "run_end",
                "status": "recovered" if failures == 0 else "recovery-errors",
            }) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        active_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"WARNING: automatic crash recovery failed: {exc}", file=sys.stderr)


def quick_hash_file(path: Path, sample_size: int = 256 * 1024) -> str:
    digest = hashlib.blake2b(digest_size=16)
    size = path.stat().st_size
    with path.open("rb") as handle:
        digest.update(handle.read(sample_size))
        if size > sample_size:
            handle.seek(max(0, size - sample_size))
            digest.update(handle.read(sample_size))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()


def find_fpcalc(script_dir: Path) -> Optional[Path]:
    candidates = [
        script_dir / "tools" / "fpcalc.exe",
        script_dir / "fpcalc.exe",
        script_dir / "tools" / "fpcalc",
    ]
    located = shutil.which("fpcalc")
    if located:
        candidates.append(Path(located))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def audio_fingerprint(
    path: Path,
    fpcalc_path: Path,
    raw: bool = False,
) -> Optional[tuple[int, Any]]:
    try:
        command = [str(fpcalc_path), "-json"]
        if raw:
            command.extend(["-length", "120", "-raw"])
        command.append(str(path))
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        payload = json.loads(completed.stdout)
        fingerprint = payload.get("fingerprint")
        duration = int(round(float(payload.get("duration") or 0)))
        if fingerprint not in (None, "", []):
            return duration, fingerprint
    except Exception:
        return None
    return None


def raw_fingerprint_values(value: Any) -> list[int]:
    if isinstance(value, list):
        output: list[int] = []
        for item in value:
            try:
                output.append(int(item))
            except (TypeError, ValueError):
                pass
        return output
    if isinstance(value, str):
        output = []
        for item in value.split(","):
            try:
                output.append(int(item.strip()))
            except ValueError:
                pass
        return output
    return []


def raw_fingerprint_similarity(left: Any, right: Any) -> float:
    left_values = raw_fingerprint_values(left)
    right_values = raw_fingerprint_values(right)
    count = min(len(left_values), len(right_values))
    if count < 16:
        return 0.0
    differing_bits = 0
    for left_value, right_value in zip(left_values[:count], right_values[:count]):
        differing_bits += ((left_value & 0xFFFFFFFF) ^ (right_value & 0xFFFFFFFF)).bit_count()
    return 1.0 - (differing_bits / float(count * 32))


def identify_by_fingerprint(
    path: Path,
    fpcalc_path: Optional[Path],
    client: CatalogClient,
    config: dict[str, Any],
) -> tuple[Optional[Candidate], list[str]]:
    api_key = str(config.get("acoustid_api_key") or "").strip()
    if (
        not bool(getattr(client, "enable_acoustid_provider", True))
        or not bool(config.get("fingerprint_identification_enabled", True))
        or not api_key
        or fpcalc_path is None
    ):
        return None, []

    fingerprint = audio_fingerprint(path, fpcalc_path)
    if not fingerprint:
        return None, ["AcoustID: fpcalc could not fingerprint the file"]

    duration, fingerprint_text = fingerprint
    if not isinstance(fingerprint_text, str):
        return None, ["AcoustID: fpcalc returned an unsupported fingerprint format"]
    try:
        payload = client.acoustid_lookup(api_key, duration, fingerprint_text)
        results = payload.get("results") or []
        if not results:
            return None, []
        ranked_results = sorted(
            results,
            key=lambda item: float(item.get("score") or 0.0),
            reverse=True,
        )
        best_result = ranked_results[0]
        score = float(best_result.get("score") or 0.0)
        minimum_score = float(config.get("fingerprint_min_score", 0.72))
        if score < minimum_score:
            return None, [
                f"AcoustID: best fingerprint score {score:.3f} is below {minimum_score:.3f}"
            ]
        recordings = best_result.get("recordings") or []
        if not recordings:
            return None, []
        recording = max(
            recordings,
            key=lambda item: (
                bool(item.get("id")),
                bool(item.get("title")),
                bool(item.get("artists")),
            ),
        )
        recording_id = str(recording.get("id") or "")
        if recording_id:
            detailed = client.musicbrainz_recording(recording_id)
            if detailed:
                candidate = musicbrainz_candidate(detailed, None)
                candidate.source = "acoustid"
                candidate.confidence = min(100.0, max(70.0, score * 100.0))
                candidate.consensus_sources = ["acoustid", "musicbrainz"]
                candidate.evidence["fingerprint_score"] = score
                return candidate, []

        title = str(recording.get("title") or "").strip()
        artists = recording.get("artists") or []
        artist = " & ".join(
            str(item.get("name") or "").strip()
            for item in artists
            if str(item.get("name") or "").strip()
        )
        release_groups = recording.get("releasegroups") or []
        album = str(release_groups[0].get("title") or "").strip() if release_groups else None
        if title and artist:
            candidate = Candidate(
                source="acoustid",
                title=title,
                artist=artist,
                album=album or None,
                album_artist=artist,
                musicbrainz_recording_id=recording_id or None,
                musicbrainz_artist_ids=[
                    str(item.get("id"))
                    for item in artists
                    if item.get("id")
                ],
                confidence=min(100.0, max(70.0, score * 100.0)),
                title_similarity=100.0,
                artist_similarity=100.0,
                consensus_sources=["acoustid"],
                evidence={
                    "fingerprint_score": score,
                    "track_artist_entities": [
                        str(item.get("name"))
                        for item in artists
                        if item.get("name")
                    ],
                    "track_artist_keys": [
                        f"mb:{item.get('id')}" if item.get("id") else ""
                        for item in artists
                        if item.get("name")
                    ],
                    "track_artist_atomic": len(artists) == 1,
                },
            )
            return candidate, []
    except Exception as exc:
        return None, [f"AcoustID: {exc}"]

    return None, []


def files_are_audio_equivalent(
    left: Path,
    right: Path,
    fpcalc_path: Optional[Path],
) -> bool:
    if fpcalc_path is None:
        return False
    left_fp = audio_fingerprint(left, fpcalc_path, raw=True)
    right_fp = audio_fingerprint(right, fpcalc_path, raw=True)
    if not left_fp or not right_fp:
        return False
    if abs(left_fp[0] - right_fp[0]) > 1:
        return False
    return raw_fingerprint_similarity(left_fp[1], right_fp[1]) >= 0.93


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def files_are_identical(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        if quick_hash_file(left) != quick_hash_file(right):
            return False
        return hash_file(left) == hash_file(right)
    except OSError:
        return False


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 10000):
        candidate = path.with_name(
            f"{path.stem} ({index}){path.suffix}"
        )
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find a unique target for: {path}")


def values_equivalent(left: Optional[str], right: Optional[str]) -> bool:
    return compact_spaces(str(left or "")) == compact_spaces(str(right or ""))


def bitrate_tags_match(path: Path, audio: AudioInfo) -> bool:
    if not audio.bitrate_bps:
        return True
    try:
        tags = ID3(path)
        bitrate_frames = tags.getall("TXXX:BITRATE")
        expected = f"{int(round(audio.bitrate_bps / 1000))} kbps"
        if not bitrate_frames or expected not in bitrate_frames[0].text:
            return False
        if audio.bitrate_mode:
            mode_frames = tags.getall("TXXX:BITRATE_MODE")
            if not mode_frames or audio.bitrate_mode not in mode_frames[0].text:
                return False
        return True
    except Exception:
        return False


def mp3_already_current(
    path: Path,
    candidate: Candidate,
    audio: AudioInfo,
    write_bitrate_tag: bool,
) -> bool:
    old = audio.tags
    expected_album_artist = candidate.album_artist or candidate.artist
    checks = [
        values_equivalent(old.title, clean_title(candidate.title, False)),
        values_equivalent(old.artist, candidate.artist),
        values_equivalent(old.albumartist, expected_album_artist),
        values_equivalent(old.album, candidate.album),
    ]
    if candidate.musicbrainz_recording_id:
        checks.append(
            values_equivalent(old.musicbrainz_trackid, candidate.musicbrainz_recording_id)
        )
    if candidate.musicbrainz_release_id:
        checks.append(
            values_equivalent(old.musicbrainz_albumid, candidate.musicbrainz_release_id)
        )
    if len(candidate.musicbrainz_artist_ids) == 1:
        checks.append(
            values_equivalent(
                old.musicbrainz_artistid,
                candidate.musicbrainz_artist_ids[0],
            )
        )
    if not all(checks):
        return False
    return not write_bitrate_tag or bitrate_tags_match(path, audio)


def process_mp3(
    source: Path,
    target: Path,
    duplicate_root: Path,
    artist_folder: str,
    album_folder: str,
    candidate: Candidate,
    audio: AudioInfo,
    copy_mode: bool,
    id3_version: str,
    write_bitrate_tag: bool,
    journal: RunJournal,
    backup_root: Path,
    fpcalc_path: Optional[Path] = None,
    fingerprint_duplicates: bool = True,
    duplicate_handling: str = "delete_exact_audio",
) -> dict[str, Any]:
    change = {
        "id": uuid.uuid4().hex,
        "kind": "mp3",
        "mode": "copy" if copy_mode else "in_place",
        "source": str(source),
        "final": str(target),
        "old_tags": asdict(audio.tags),
        "candidate": asdict(candidate),
        "status": "pending",
        "error": None,
    }

    if (
        not copy_mode
        and same_path(source, target)
        and mp3_already_current(source, candidate, audio, write_bitrate_tag)
    ):
        change["status"] = "unchanged"
        return change

    # Existing target: separate duplicates before any tag mutation.
    if target.exists() and not same_path(source, target):
        exact = files_are_identical(source, target)
        audio_equivalent = False
        if not exact and fingerprint_duplicates:
            audio_equivalent = files_are_audio_equivalent(
                source,
                target,
                fpcalc_path,
            )

        if exact:
            category = "Exact"
            status = "duplicate-exact"
        elif audio_equivalent:
            category = "Audio_Equivalent"
            status = "duplicate-audio"
        else:
            category = "Conflicts"
            status = "duplicate-conflict"

        handling = str(duplicate_handling or "delete_exact_audio").strip().lower()
        if handling in {"delete", "delete_exact_audio", "remove"} and status in {"duplicate-exact", "duplicate-audio"}:
            change["final"] = str(target)
            change = journal.begin(change)
            try:
                if copy_mode:
                    change["status"] = "duplicate-skipped"
                else:
                    source.unlink()
                    change["status"] = "duplicate-deleted"
            except Exception as exc:
                change["status"] = "error"
                change["error"] = str(exc)
            journal.finish(change)
            return change

        duplicate_target = unique_target(
            duplicate_root
            / category
            / artist_folder
            / album_folder
            / target.name
        )
        duplicate_target.parent.mkdir(parents=True, exist_ok=True)
        change["final"] = str(duplicate_target)
        change = journal.begin(change)
        try:
            if copy_mode:
                shutil.copy2(source, duplicate_target)
            else:
                safe_rename(source, duplicate_target)
            change["status"] = status
        except Exception as exc:
            change["status"] = "error"
            change["error"] = str(exc)
        journal.finish(change)
        return change

    if copy_mode:
        temporary = target.parent / (
            f".__smart_music_copy_{uuid.uuid4().hex}.mp3"
        )
        change["staging"] = str(temporary)
        change = journal.begin(change)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, temporary)
            write_tags(
                temporary,
                candidate,
                audio.tags,
                audio,
                id3_version,
                write_bitrate_tag,
            )
            if target.exists():
                raise FileExistsError(f"Target appeared during copy: {target}")
            safe_rename(temporary, target)
            change["status"] = "applied"
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            change["status"] = "error"
            change["error"] = str(exc)
        journal.finish(change)
        return change

    # In-place mode is transactional: move original to a temporary sibling,
    # mutate only the temporary file, then commit it to the final path.
    backup_path = backup_root / f"{change['id']}.id3"
    staging = source.with_name(
        f".__smart_music_txn_{change['id']}{source.suffix}"
    )
    change["tag_snapshot"] = str(backup_path)
    change["staging"] = str(staging)

    try:
        snapshot_id3(source, backup_path)
        change = journal.begin(change)
        safe_rename(source, staging)
        write_tags(
            staging,
            candidate,
            audio.tags,
            audio,
            id3_version,
            write_bitrate_tag,
        )
        if target.exists() and not same_path(staging, target):
            raise FileExistsError(f"Target appeared during commit: {target}")
        safe_rename(staging, target)
        change["status"] = "applied"
    except Exception as exc:
        change["error"] = str(exc)
        ok, rollback_message = rollback_pending_change(change, id3_version)
        change["status"] = "rolled-back-error" if ok else "error"
        if not ok:
            change["error"] = f"{exc}; rollback failed: {rollback_message}"
    journal.finish(change)
    return change


def protected_top_level_names(config: dict[str, Any]) -> set[str]:
    return {
        str(config["other_files_folder"]).casefold(),
        str(config["duplicates_folder"]).casefold(),
    }


def scan_library(
    root: Path,
    config: dict[str, Any],
    excluded_roots: Optional[list[Path]] = None,
) -> tuple[list[Path], list[Path]]:
    mp3_files: list[Path] = []
    other_files: list[Path] = []
    protected = protected_top_level_names(config)
    excluded = [path.resolve() for path in (excluded_roots or [])]

    for current_dir, dir_names, file_names in os.walk(root):
        current = Path(current_dir)

        filtered_dirs: list[str] = []
        for name in dir_names:
            candidate = current / name
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                relative = Path(name)

            if (
                len(relative.parts) == 1
                and relative.parts[0].casefold() in protected
            ):
                continue
            if any(path_is_within(candidate, item) for item in excluded):
                continue
            if name.startswith(".__smart_music_"):
                continue
            if bool(config.get("skip_symlinks", True)) and candidate.is_symlink():
                continue
            filtered_dirs.append(name)

        dir_names[:] = filtered_dirs

        for file_name in file_names:
            if file_name.startswith(".__smart_music_"):
                continue
            path = current / file_name
            if any(path_is_within(path, item) for item in excluded):
                continue
            if bool(config.get("skip_symlinks", True)) and path.is_symlink():
                continue
            if path.suffix.casefold() == MP3_EXTENSION:
                mp3_files.append(path)
            else:
                other_files.append(path)

    mp3_files.sort(key=lambda path: str(path).casefold())
    other_files.sort(key=lambda path: str(path).casefold())
    return mp3_files, other_files


def other_file_target(
    source: Path,
    input_root: Path,
    output_root: Path,
    other_files_folder: str,
) -> Path:
    try:
        relative = source.relative_to(input_root)
    except ValueError:
        relative = Path(source.name)

    extension_name = (
        source.suffix.lower().lstrip(".")
        if source.suffix
        else "_no_extension"
    )

    return (
        output_root
        / other_files_folder
        / extension_name
        / relative
    )


def fit_other_file_target(
    target: Path,
    output_root: Path,
    other_files_folder: str,
    max_path_length: int,
) -> Path:
    if len(str(target)) <= max_path_length:
        return target
    digest = hashlib.sha1(str(target).encode("utf-8")).hexdigest()[:12]
    stem = sanitize_component(target.stem, False)
    stem = truncate_name(stem, 80)
    suffix = target.suffix[:20]
    fallback = (
        output_root
        / other_files_folder
        / "_Long_Paths"
        / f"{stem}__{digest}{suffix}"
    )
    if len(str(fallback)) > max_path_length:
        stem = truncate_name(stem, max(12, 80 - (len(str(fallback)) - max_path_length)))
        fallback = (
            output_root
            / other_files_folder
            / "_Long_Paths"
            / f"{stem}__{digest}{suffix}"
        )
    return fallback


def process_other_file(
    source: Path,
    target: Path,
    copy_mode: bool,
    journal: RunJournal,
    status: str = "moved-other-file",
) -> dict[str, Any]:
    change = {
        "id": uuid.uuid4().hex,
        "kind": "other",
        "mode": "copy" if copy_mode else "in_place",
        "source": str(source),
        "final": str(target),
        "status": "pending",
        "error": None,
    }

    if not copy_mode and same_path(source, target):
        change["status"] = (
            "unchanged-sidecar"
            if status == "moved-sidecar"
            else "unchanged-other-file"
        )
        return change

    target = unique_target(target) if target.exists() else target
    change["final"] = str(target)
    if copy_mode:
        staging = target.with_name(
            f".__smart_music_copy_{uuid.uuid4().hex}{target.suffix}"
        )
    else:
        staging = source.with_name(
            f".__smart_music_txn_{change['id']}{source.suffix}"
        )
    change["staging"] = str(staging)
    change = journal.begin(change)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy_mode:
            shutil.copy2(source, staging)
            safe_rename(staging, target)
        else:
            safe_rename(source, staging)
            safe_rename(staging, target)
        change["status"] = status
    except Exception as exc:
        change["error"] = str(exc)
        ok, rollback_message = rollback_pending_change(change, "2.3")
        change["status"] = "rolled-back-error" if ok else "error"
        if not ok:
            change["error"] = f"{exc}; rollback failed: {rollback_message}"
    journal.finish(change)
    return change


def sidecar_extensions(config: dict[str, Any]) -> set[str]:
    return {
        str(value).casefold()
        for value in config.get("sidecar_extensions", [])
        if str(value).startswith(".")
    }


def sidecar_target_for(
    source: Path,
    album_targets_by_source_dir: dict[Path, Counter[Path]],
    config: dict[str, Any],
    track_targets_by_source_stem: Optional[dict[tuple[Path, str], Path]] = None,
) -> Optional[Path]:
    if not bool(config.get("preserve_sidecars", True)):
        return None
    if source.suffix.casefold() not in sidecar_extensions(config):
        return None

    # Track-specific lyrics should follow the renamed MP3 filename.
    if source.suffix.casefold() == ".lrc" and track_targets_by_source_stem:
        track_target = track_targets_by_source_stem.get(
            (source.parent, source.stem.casefold())
        )
        if track_target is not None:
            return track_target.with_suffix(source.suffix.lower())

    candidates = album_targets_by_source_dir.get(source.parent)
    if not candidates:
        return None
    album_dir, _ = candidates.most_common(1)[0]
    return album_dir / source.name


def remove_empty_directories(
    root: Path,
    config: dict[str, Any],
) -> int:
    protected = protected_top_level_names(config)
    removed = 0

    directories = [
        Path(current)
        for current, _, _ in os.walk(root)
    ]
    directories.sort(
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for directory in directories:
        if directory == root:
            continue

        try:
            relative = directory.relative_to(root)
        except ValueError:
            continue

        if relative.parts and relative.parts[0].casefold() in protected:
            continue

        try:
            directory.rmdir()
            removed += 1
        except OSError:
            pass

    return removed


def load_config(script_dir: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    path = script_dir / "config.json"

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
                if (
                    "album_subfolders_enabled" not in loaded
                    and "artist_subfolders_enabled" in loaded
                ):
                    config["album_subfolders_enabled"] = bool(
                        loaded["artist_subfolders_enabled"]
                    )
        except (OSError, json.JSONDecodeError):
            pass

    load_local_registries(script_dir, config)
    return config


def write_csv(path: Path, results: list[Result]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "item_type",
        "source_path",
        "old_filename",
        "new_filename",
        "status",
        "match_source",
        "confidence",
        "title",
        "artist",
        "artist_folder",
        "filename_artist",
        "album",
        "album_folder",
        "bitrate_kbps",
        "bitrate_mode",
        "consensus_sources",
        "folder_reason",
        "final_path",
        "error",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for result in results:
            writer.writerow(asdict(result))


def undo_manifest(path: Path) -> int:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    id3_version = str(manifest.get("id3_version", "2.3"))
    restored = 0
    failures = 0
    successful_statuses = {
        "applied",
        "moved-other-file",
        "moved-sidecar",
        "duplicate-exact",
        "duplicate-audio",
        "duplicate-conflict",
    }

    for change in reversed(manifest.get("changes", [])):
        if change.get("status") not in successful_statuses:
            continue

        original = Path(change["source"])
        current = Path(change["final"])
        mode = change.get("mode")

        try:
            if mode == "copy":
                if current.exists():
                    current.unlink()
                restored += 1
                print(f"REMOVED COPY: {current}")
                continue

            if not current.exists():
                raise FileNotFoundError(
                    f"Current file was not found: {current}"
                )

            if original.exists() and not same_path(original, current):
                raise FileExistsError(
                    f"Original path is occupied: {original}"
                )

            if change.get("kind") == "mp3":
                snapshot_value = str(change.get("tag_snapshot") or "")
                if snapshot_value and Path(snapshot_value).exists():
                    restore_id3_snapshot(
                        current,
                        Path(snapshot_value),
                        id3_version,
                    )
                elif change.get("old_tags"):
                    # Backward compatibility with v6 manifests.
                    restore_tags(
                        current,
                        change["old_tags"],
                        id3_version,
                    )

            original.parent.mkdir(parents=True, exist_ok=True)
            safe_rename(current, original)

            restored += 1
            print(f"RESTORED: {original}")
        except Exception as exc:
            failures += 1
            print(f"UNDO ERROR: {exc}", file=sys.stderr)

    print()
    print(f"Restored: {restored}")
    print(f"Failures: {failures}")
    return 0 if failures == 0 else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Organize an MP3 library into canonical Artist/Album folders with deterministic collaboration filenames."
        )
    )
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--copy-to", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--default-artist")
    parser.add_argument("--verify-all-online", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--min-confidence", type=float)
    parser.add_argument("--normalize-persian", action="store_true")
    parser.add_argument(
        "--id3-version",
        choices=["2.3", "2.4"],
        default="2.3",
    )
    parser.add_argument("--undo", type=Path)
    return parser.parse_args()


def should_print_progress(index: int, total: int, every: int) -> bool:
    every = max(1, int(every or 1))
    return index <= 5 or index == total or index % every == 0


def filename_conflicts_with_existing_tags(
    source: Path,
    audio: AudioInfo,
    normalize_persian: bool,
    config: dict[str, Any],
) -> bool:
    if not audio.tags.title or not audio.tags.artist:
        return False

    stem = clean_title(source.stem, normalize_persian)
    parts = [
        compact_spaces(part)
        for part in stem.split(" - ")
        if compact_spaces(part)
    ]
    if len(parts) < 2:
        return False

    raw_pairs = [
        (" - ".join(parts[:-1]), parts[-1]),
        (" - ".join(parts[1:]), parts[0]),
    ]
    agreements: list[float] = []
    for raw_title, raw_artist in raw_pairs:
        title = clean_title(raw_title, normalize_persian)
        artist = clean_artist_label(raw_artist, normalize_persian, config)
        if not title or not meaningful_artist_label(artist):
            continue
        agreements.append(
            (
                similarity(audio.tags.title, title)
                + similarity(audio.tags.artist, artist)
            )
            / 2.0
        )

    return bool(agreements) and max(agreements) < 45.0


def online_candidate_conflicts_with_local_performer(
    online_candidate: Optional[Candidate],
    audio: AudioInfo,
    normalize_persian: bool,
    config: dict[str, Any],
) -> bool:
    """Protect a strong single local performer from secondary-credit drift."""
    if online_candidate is None:
        return False
    if online_candidate.evidence.get("exact_isrc") or audio.tags.musicbrainz_trackid:
        return False

    local_refs = text_artist_refs(audio.tags.artist, normalize_persian, config)
    if len(local_refs) != 1:
        return False

    track_refs = candidate_artist_refs(
        online_candidate,
        album=False,
        normalize_persian=normalize_persian,
        config=config,
    )
    if len(track_refs) <= 1:
        return False

    local_match = matching_ref(track_refs, local_refs[0].name)
    if local_match is None:
        return True

    match_index = next(
        (
            index
            for index, ref in enumerate(track_refs)
            if refs_equivalent(ref, local_match)
        ),
        0,
    )
    if match_index == 0:
        return False

    album_refs = candidate_artist_refs(
        online_candidate,
        album=True,
        normalize_persian=normalize_persian,
        config=config,
    )
    if any(refs_equivalent(local_match, ref) for ref in album_refs):
        return False

    return True


def determine_candidate(
    source: Path,
    audio: AudioInfo,
    default_artist: str,
    normalize_persian: bool,
    config: dict[str, Any],
    client: CatalogClient,
    min_confidence: float,
    verify_online: bool,
    offline: bool,
    unknown_artist_folder: str,
    fpcalc_path: Optional[Path] = None,
) -> tuple[Candidate, list[str]]:
    seeds = generate_seeds(
        source,
        audio.tags,
        default_artist or None,
        normalize_persian,
        config,
    )
    candidate = candidate_from_existing_tags(
        audio,
        normalize_persian,
        config,
    )
    lookup_errors: list[str] = []

    cleaned_existing_artist = clean_artist_label(
        audio.tags.artist,
        normalize_persian,
        config,
    )
    cleaned_existing_album = clean_album_label(
        audio.tags.album,
        audio.tags.title,
        normalize_persian,
        config,
    )

    identity_problem = bool(
        candidate is None
        or text_was_dirty(audio.tags.title)
        or filename_conflicts_with_existing_tags(source, audio, normalize_persian, config)
        or not meaningful_artist_label(cleaned_existing_artist)
    )
    only_missing_album = bool(
        candidate is not None
        and cleaned_existing_album is None
        and not identity_problem
        and not verify_online
    )
    should_lookup = bool(
        not offline
        and seeds
        and (identity_problem or verify_online or only_missing_album)
    )
    online_accepted = False

    if should_lookup:
        online_candidate: Optional[Candidate] = None
        if only_missing_album:
            online_candidate, fast_errors = identify_fast_catalog(
                audio,
                seeds,
                client,
            )
            lookup_errors.extend(fast_errors)

        fast_conflict = online_candidate_conflicts_with_local_performer(
            online_candidate,
            audio,
            normalize_persian,
            config,
        )
        online_accepted = bool(
            online_candidate
            and online_candidate.confidence >= min_confidence
            and online_candidate.title_similarity >= 80
            and online_candidate.artist_similarity >= 78
            and not fast_conflict
        )

        if not online_accepted:
            online_candidate, full_errors = identify_online(
                audio,
                seeds,
                client,
                config,
            )
            lookup_errors.extend(full_errors)
            full_conflict = online_candidate_conflicts_with_local_performer(
                online_candidate,
                audio,
                normalize_persian,
                config,
            )
            online_accepted = bool(
                online_candidate
                and online_candidate.confidence >= min_confidence
                and (
                    online_candidate.title_similarity >= 74
                    or online_candidate.evidence.get("exact_isrc")
                    or audio.tags.musicbrainz_trackid
                )
                and (
                    online_candidate.artist_similarity >= 72
                    or online_candidate.evidence.get("exact_isrc")
                    or audio.tags.musicbrainz_trackid
                )
                and not full_conflict
            )

        if online_accepted and online_candidate is not None:
            candidate = online_candidate

    fingerprint_uncertain = bool(
        candidate is None
        or identity_problem
        or (
            bool(config.get("fingerprint_when_uncertain", True))
            and should_lookup
            and not online_accepted
        )
        or (
            bool(config.get("fingerprint_when_uncertain", True))
            and candidate is not None
            and candidate.confidence < min_confidence
        )
    )
    if not offline and fingerprint_uncertain:
        fingerprint_candidate, fingerprint_errors = identify_by_fingerprint(
            source,
            fpcalc_path,
            client,
            config,
        )
        lookup_errors.extend(fingerprint_errors)
        if fingerprint_candidate is not None:
            local_confidence = candidate.confidence if candidate is not None else 0.0
            fingerprint_score = float(
                fingerprint_candidate.evidence.get("fingerprint_score") or 0.0
            )
            # A strong acoustic identity is more reliable than filename cleanup
            # or a suspicious local tag. Keep a high-confidence accepted online
            # candidate unless the fingerprint is exceptionally strong.
            if (
                candidate is None
                or candidate.source in {"local-cleanup", "unknown-fallback"}
                or (not online_accepted and identity_problem)
                or fingerprint_candidate.confidence >= local_confidence + 3.0
                or fingerprint_score >= 0.92
            ):
                fingerprint_candidate.evidence["replaced_candidate_source"] = (
                    candidate.source if candidate is not None else None
                )
                candidate = fingerprint_candidate

    registry_candidate = local_registry_candidate(
        audio,
        seeds,
        normalize_persian,
        config,
    )
    if registry_candidate is not None:
        if (
            candidate is None
            or candidate.source in {"local-cleanup", "unknown-fallback", "existing-tags"}
            or candidate.confidence < float(config.get("registry_confidence", 91.0))
        ):
            registry_candidate.evidence["replaced_candidate_source"] = (
                candidate.source if candidate is not None else None
            )
            candidate = registry_candidate

    if candidate is None:
        candidate = local_cleanup_candidate(
            audio,
            seeds,
            normalize_persian,
            config,
        )

    if candidate is None:
        candidate = unknown_fallback_candidate(
            source,
            audio,
            unknown_artist_folder,
            normalize_persian,
            config,
        )

    candidate.title = clean_title(candidate.title, normalize_persian)
    candidate.artist = clean_artist_label(
        candidate.artist,
        normalize_persian,
        config,
    )
    candidate.album = clean_album_label(
        candidate.album or audio.tags.album,
        candidate.title,
        normalize_persian,
        config,
    )
    if not meaningful_artist_label(candidate.artist):
        candidate.artist = (
            unknown_artist_folder.lstrip("_ ").strip()
            or "Unknown Artist"
        )
    if not meaningful_artist_label(candidate.album_artist):
        candidate.album_artist = candidate.artist

    return candidate, lookup_errors


def main() -> int:
    configure_console()
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    config = load_config(script_dir)
    if args.workers is not None:
        config["scan_workers"] = max(1, int(args.workers))

    app_dir = app_data_dir()
    app_lock = AppRunLock(app_dir)
    if not app_lock.acquire():
        print(
            "Another Smart Music Organizer instance is already running.",
            file=sys.stderr,
        )
        return 2
    atexit.register(app_lock.release)

    recover_active_run(app_dir)

    learning_registry: Optional[LearningRegistry] = None
    learned_loaded = 0
    if bool(config.get("learning_registry_enabled", True)):
        learning_registry = LearningRegistry(app_dir / "learning_registry.sqlite3", config)
        learned_loaded = merge_learning_registry_into_config(learning_registry, config)

    if args.undo:
        return undo_manifest(args.undo)

    folder = args.folder or select_folder_gui(
        "Select the root music library folder"
    )
    if folder is None:
        entered = input("Music library folder path: ").strip().strip('"')
        folder = Path(entered) if entered else None

    if folder is None or not folder.exists() or not folder.is_dir():
        print("A valid music library folder was not selected.", file=sys.stderr)
        return 2

    input_root = folder.resolve()
    output_root = args.copy_to.resolve() if args.copy_to else input_root
    copy_mode = args.copy_to is not None

    if copy_mode and same_path(input_root, output_root):
        print("Input and output folders cannot be the same.", file=sys.stderr)
        return 2
    if copy_mode and path_is_within(output_root, input_root):
        print(
            "The output folder cannot be inside the input library. "
            "Choose a separate folder to prevent recursive reprocessing.",
            file=sys.stderr,
        )
        return 2

    default_artist = (
        args.default_artist
        if args.default_artist is not None
        else str(config.get("default_artist") or "")
    )
    min_confidence = (
        args.min_confidence
        if args.min_confidence is not None
        else float(config.get("min_confidence", 85))
    )
    verify_online = bool(
        args.verify_all_online
        or config.get("verify_existing_tags_online", False)
    )

    mp3_files, other_files = scan_library(input_root, config)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = app_dir / "reports" / timestamp
    csv_path = run_dir / "report.csv"
    cache_path = app_dir / "catalog_cache.sqlite3"
    backup_root = run_dir / "tag_backups"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Reuse the bundled cache once, if the user has no application cache yet.
    bundled_cache = script_dir / "catalog_cache.sqlite3"
    if not cache_path.exists() and bundled_cache.exists():
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled_cache, cache_path)
        except OSError:
            pass

    cache = Cache(cache_path)
    client = CatalogClient(
        cache=cache,
        musicbrainz_contact=str(config.get("musicbrainz_contact", "")),
        spotify_client_id=str(config.get("spotify_client_id", "")),
        spotify_client_secret=str(config.get("spotify_client_secret", "")),
        apple_country=str(config.get("apple_country", "US")),
    )
    client.enable_musicbrainz_provider = provider_enabled(config, "musicbrainz", True)
    client.enable_apple_provider = provider_enabled(config, "apple_itunes", True)
    client.enable_spotify_provider = provider_enabled(config, "spotify", False)
    client.enable_acoustid_provider = provider_enabled(config, "acoustid", True)
    client.spotify_market = str(config.get("spotify_market", "") or "")
    client.spotify_cache_days = int(config.get("spotify_cache_days", 30) or 30)
    client.spotify_search_limit = int(config.get("spotify_search_limit", 10) or 10)

    other_files_folder = str(config["other_files_folder"])
    unknown_artist_folder = str(config["unknown_artist_folder"])
    duplicates_folder = str(config["duplicates_folder"])
    duplicate_root = output_root / duplicates_folder
    fpcalc_path = find_fpcalc(script_dir)

    mode = "copy" if copy_mode else ("apply" if args.apply else "preview")
    progress_every = max(1, int(config.get("progress_every", 25)))
    journal = RunJournal(
        run_dir=run_dir,
        app_dir=app_dir,
        metadata={
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_version": APP_VERSION,
            "input_root": str(input_root),
            "output_root": str(output_root),
            "mode": mode,
            "id3_version": args.id3_version,
        },
        fsync=bool(config.get("journal_fsync", True)),
    )

    print(f"Smart Music Organizer v{APP_VERSION}")
    print(f"Input library: {input_root}")
    print(f"Output library: {output_root}")
    print(f"MP3 files: {len(mp3_files)}")
    print(f"Non-MP3 files: {len(other_files)}")
    print(f"Mode: {mode.upper()}")
    print(f"Local scan workers: {configured_worker_count(config)}")
    print(f"Online verification of valid tags: {'ON' if verify_online else 'OFF'}")
    print(f"Offline mode: {'ON' if args.offline else 'OFF'}")
    fingerprint_id_on = bool(
        fpcalc_path
        and str(config.get("acoustid_api_key") or "").strip()
        and bool(config.get("fingerprint_identification_enabled", True))
    )
    enabled_provider_names = [
        name
        for name, enabled in (config.get("online_providers") or {}).items()
        if enabled
    ]
    print(f"Free-first mode: {'ON' if config.get('free_first_mode', True) else 'OFF'}")
    print(f"Online providers: {', '.join(enabled_provider_names) if enabled_provider_names else 'OFF'}")
    print(f"Local JSON registry: {'ON' if config.get('local_registry_enabled', True) else 'OFF'}")
    print(f"Automatic learning registry: {'ON' if learning_registry is not None else 'OFF'} ({learned_loaded} learned artists loaded)")
    print(f"Fingerprint identification: {'ON' if fingerprint_id_on and provider_enabled(config, 'acoustid', True) else 'OFF (AcoustID key/fpcalc required)'}")
    print(f"Fingerprint duplicate check: {'ON' if fpcalc_path else 'OFF (fpcalc not found)'}")
    print(f"Artist layout: {'Artist / Album' if config.get('album_subfolders_enabled', True) else 'Artist only'}")
    print(f"Artist folder style: {config.get('artist_folder_name_style', 'snake_case')}")
    print(f"Reports: {run_dir}")
    print()

    results: list[Result] = []
    run_completed = False
    removed_empty = 0

    try:
        print("Phase 1/4: reading local metadata...")
        audio_cache, read_errors = read_audio_cache_parallel(mp3_files, config)
        for source, error in read_errors.items():
            results.append(
                Result(
                    item_type="mp3",
                    source_path=str(source),
                    old_filename=source.name,
                    new_filename=None,
                    status="skipped-read-error",
                    match_source=None,
                    confidence=None,
                    title=None,
                    artist=None,
                    artist_folder=None,
                    filename_artist=None,
                    album=None,
                    album_folder=None,
                    bitrate_kbps=None,
                    bitrate_mode=None,
                    consensus_sources="",
                    error=error,
                )
            )

        if learning_registry is not None:
            print("Phase 1b/4: learning from existing folders and tags...")
            learning_stats = auto_learn_from_library(
                input_root=input_root,
                mp3_files=mp3_files,
                audio_cache=audio_cache,
                normalize_persian=args.normalize_persian,
                config=config,
                learning=learning_registry,
                run_dir=run_dir,
            )
            learned_loaded = merge_learning_registry_into_config(learning_registry, config)
            print(
                "  Learned/observed: "
                f"{learning_stats['artists']} artists, "
                f"{learning_stats['aliases']} aliases, "
                f"{learning_stats['observations']} observations, "
                f"{learning_stats['recordings']} recordings "
                f"({learned_loaded} learned artists available)"
            )

        print("Phase 2/4: identifying tracks...")
        plans: list[TrackPlan] = []
        readable_files = [path for path in mp3_files if path in audio_cache]
        for index, source in enumerate(readable_files, start=1):
            audio = audio_cache[source]
            candidate, lookup_errors = determine_candidate(
                source=source,
                audio=audio,
                default_artist=default_artist,
                normalize_persian=args.normalize_persian,
                config=config,
                client=client,
                min_confidence=min_confidence,
                verify_online=verify_online,
                offline=args.offline,
                unknown_artist_folder=unknown_artist_folder,
                fpcalc_path=fpcalc_path,
            )
            plans.append(
                TrackPlan(
                    source=source,
                    audio=audio,
                    candidate=candidate,
                    lookup_errors=lookup_errors,
                )
            )
            if should_print_progress(index, len(readable_files), progress_every):
                print(
                    f"  [{index}/{len(readable_files)}] "
                    f"{source.name} -> {candidate.title} / {candidate.artist} "
                    f"[{candidate.source} {candidate.confidence:.0f}%]"
                )

        print("Phase 3/4: resolving artist identities and destinations...")
        resolved_identities, identity_errors = resolve_artist_identities_online(
            plans,
            client,
            config,
            args.offline,
        )
        if resolved_identities:
            print(f"  Resolved artist identity references: {resolved_identities}")
        if identity_errors:
            print(
                f"  Artist identity lookup warnings: {len(identity_errors)}"
            )

        profile = build_profile_from_plans(
            plans,
            args.normalize_persian,
            config,
        )
        album_targets_by_source_dir: dict[Path, Counter[Path]] = defaultdict(Counter)
        track_targets_by_source_stem: dict[tuple[Path, str], Path] = {}

        preliminary_album_counts: Counter[tuple[str, str]] = Counter()

        for plan in plans:
            candidate = plan.candidate
            audio = plan.audio
            artist_folder = primary_artist_for_folder(
                candidate,
                audio.tags,
                profile,
                unknown_artist_folder,
                args.normalize_persian,
                config,
                candidate.album,
            )
            raw_album_folder = album_folder_for(
                candidate,
                audio.tags,
                artist_folder,
                profile,
                args.normalize_persian,
                config,
            )
            filename_artist = output_artist_credit(
                candidate,
                audio.tags,
                profile,
                args.normalize_persian,
                config,
            )
            plan.artist_folder = artist_folder
            plan.filename_artist = filename_artist
            plan.album_folder = raw_album_folder
            if raw_album_folder and not is_singles_folder(raw_album_folder, config):
                preliminary_album_counts[(artist_folder, raw_album_folder)] += 1

        for plan in plans:
            candidate = plan.candidate
            audio = plan.audio
            artist_folder = str(plan.artist_folder)
            raw_album_folder = str(plan.album_folder or "")
            album_count = preliminary_album_counts.get((artist_folder, raw_album_folder), 0)
            album_folder = reliable_album_folder_for(
                raw_album_folder,
                candidate,
                audio.tags,
                album_count,
                args.normalize_persian,
                config,
            )
            album_folder = destination_album_folder(album_folder, config)
            filename_artist = str(plan.filename_artist or output_artist_credit(
                candidate,
                audio.tags,
                profile,
                args.normalize_persian,
                config,
            ))
            new_filename = build_filename(
                candidate.title,
                filename_artist,
                args.normalize_persian,
            )
            artist_folder, album_folder, new_filename, target = fit_target_path(
                output_root,
                artist_folder,
                album_folder,
                new_filename,
                int(config.get("max_path_length", 240)),
            )
            plan.artist_folder = artist_folder
            plan.filename_artist = filename_artist
            plan.album_folder = album_folder
            plan.target = target
            album_targets_by_source_dir[plan.source.parent][target.parent] += 1
            track_targets_by_source_stem[(plan.source.parent, plan.source.stem.casefold())] = target

        print("Phase 4/4: applying plan..." if mode != "preview" else "Phase 4/4: writing preview...")
        for index, plan in enumerate(plans, start=1):
            source = plan.source
            audio = plan.audio
            candidate = plan.candidate
            artist_folder = str(plan.artist_folder)
            album_folder = str(plan.album_folder)
            target = Path(plan.target)
            bitrate_kbps = (
                int(round(audio.bitrate_bps / 1000))
                if audio.bitrate_bps
                else None
            )

            if mode == "preview":
                status = "preview"
                final_path = str(target)
                error = "; ".join(plan.lookup_errors) or None
                if should_print_progress(index, len(plans), progress_every):
                    print(f"  [{index}/{len(plans)}] PREVIEW -> {target}")
            else:
                change = process_mp3(
                    source=source,
                    target=target,
                    duplicate_root=duplicate_root,
                    artist_folder=artist_folder,
                    album_folder=album_folder,
                    candidate=candidate,
                    audio=audio,
                    copy_mode=copy_mode,
                    id3_version=args.id3_version,
                    write_bitrate_tag=bool(config.get("write_bitrate_tag", True)),
                    journal=journal,
                    backup_root=backup_root,
                    fpcalc_path=fpcalc_path,
                    fingerprint_duplicates=bool(config.get("fingerprint_duplicates", True)),
                    duplicate_handling=str(config.get("duplicate_handling", "delete_exact_audio")),
                )
                status = str(change["status"])
                final_path = str(change["final"])
                error = change.get("error") or ("; ".join(plan.lookup_errors) or None)
                if (
                    status in {"error", "rolled-back-error"}
                    or should_print_progress(index, len(plans), progress_every)
                ):
                    print(f"  [{index}/{len(plans)}] {status.upper()} -> {final_path}")

            results.append(
                Result(
                    item_type="mp3",
                    source_path=str(source),
                    old_filename=source.name,
                    new_filename=Path(final_path).name,
                    status=status,
                    match_source=candidate.source,
                    confidence=round(candidate.confidence, 2),
                    title=candidate.title,
                    artist=candidate.artist,
                    artist_folder=artist_folder,
                    filename_artist=str(plan.filename_artist or candidate.artist),
                    album=candidate.album,
                    album_folder=album_folder,
                    bitrate_kbps=bitrate_kbps,
                    bitrate_mode=audio.bitrate_mode,
                    consensus_sources=",".join(candidate.consensus_sources),
                    folder_reason=str(
                        candidate.evidence.get("folder_identity_reason") or ""
                    ),
                    final_path=final_path,
                    error=error,
                )
            )

        if config.get("move_non_mp3", True):
            for index, source in enumerate(other_files, start=1):
                sidecar_target = sidecar_target_for(
                    source,
                    album_targets_by_source_dir,
                    config,
                    track_targets_by_source_stem,
                )
                if sidecar_target is not None:
                    target = sidecar_target
                    applied_status = "moved-sidecar"
                    preview_status = "preview-sidecar"
                else:
                    target = other_file_target(
                        source,
                        input_root,
                        output_root,
                        other_files_folder,
                    )
                    target = fit_other_file_target(
                        target,
                        output_root,
                        other_files_folder,
                        int(config.get("max_path_length", 240)),
                    )
                    applied_status = "moved-other-file"
                    preview_status = "preview-other-file"

                if mode == "preview":
                    status = preview_status
                    final_path = str(target)
                    error = None
                    if should_print_progress(index, len(other_files), progress_every):
                        print(f"  [OTHER {index}/{len(other_files)}] PREVIEW -> {target}")
                else:
                    change = process_other_file(
                        source,
                        target,
                        copy_mode,
                        journal,
                        applied_status,
                    )
                    status = str(change["status"])
                    final_path = str(change["final"])
                    error = change.get("error")
                    if (
                        status in {"error", "rolled-back-error"}
                        or should_print_progress(index, len(other_files), progress_every)
                    ):
                        print(f"  [OTHER {index}/{len(other_files)}] {status.upper()} -> {final_path}")

                results.append(
                    Result(
                        item_type="other",
                        source_path=str(source),
                        old_filename=source.name,
                        new_filename=Path(final_path).name,
                        status=status,
                        match_source=None,
                        confidence=None,
                        title=None,
                        artist=None,
                        artist_folder=None,
                        filename_artist=None,
                        album=None,
                        album_folder=None,
                        bitrate_kbps=None,
                        bitrate_mode=None,
                        consensus_sources="",
                        final_path=final_path,
                        error=error,
                    )
                )

        if (
            args.apply
            and not copy_mode
            and config.get("remove_empty_folders", True)
        ):
            removed_empty = remove_empty_directories(input_root, config)

        write_csv(csv_path, results)
        contribution_stats: dict[str, int] = {}
        if learning_registry is not None and bool(config.get("export_learning_contributions", True)):
            contribution_stats = learning_registry.export_contributions(
                run_dir / "contributions",
                float(config.get("learning_registry_min_confidence", 86.0)),
            )
        errors = sum(
            1
            for result in results
            if result.status in {"error", "rolled-back-error"}
        )
        journal.close(
            status="completed" if errors == 0 else "completed-with-errors",
            extra={
                "removed_empty_folders": removed_empty,
                "learning_contributions": contribution_stats,
            },
        )
        run_completed = True
    except KeyboardInterrupt:
        print("\nInterrupted. Pending transaction recovery will run automatically next time.", file=sys.stderr)
        raise
    finally:
        cache.close()
        if learning_registry is not None:
            learning_registry.close()
        if not run_completed:
            # Keep the active-run pointer and append-only journal for recovery.
            try:
                journal.compact_manifest("interrupted")
            except Exception:
                pass

    applied = sum(1 for result in results if result.status == "applied")
    sidecars = sum(1 for result in results if result.status == "moved-sidecar")
    other_moved = sum(1 for result in results if result.status == "moved-other-file")
    duplicates = sum(
        1
        for result in results
        if result.status in {"duplicate-exact", "duplicate-audio", "duplicate-conflict"}
    )
    previews = sum(1 for result in results if result.status.startswith("preview"))
    unchanged = sum(1 for result in results if result.status.startswith("unchanged"))
    skipped = sum(1 for result in results if result.status.startswith("skipped"))
    errors = sum(
        1
        for result in results
        if result.status in {"error", "rolled-back-error"}
    )

    print()
    print("=" * 76)
    print(f"MP3 files organized: {applied}")
    print(f"Sidecar files kept with albums: {sidecars}")
    print(f"Other files moved: {other_moved}")
    print(f"Duplicates separated: {duplicates}")
    print(f"Preview items: {previews}")
    print(f"Already organized / unchanged: {unchanged}")
    print(f"Skipped: {skipped}")
    print(f"Errors safely rolled back / failed: {errors}")
    print(f"Empty folders removed: {removed_empty}")
    print(f"CSV report: {csv_path}")
    print(f"Undo manifest: {journal.manifest_path}")

    if mode == "preview":
        print("\nNo files were changed because --apply was not used.")

    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
