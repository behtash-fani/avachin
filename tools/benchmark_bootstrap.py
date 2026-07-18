#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a reviewable benchmark manifest from Avachin's local fingerprint DB."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from tools.benchmark_contract import BENCHMARK_SCHEMA_VERSION

_VERSION_MARKERS = {
    "live": ("live", "concert", "زنده"),
    "remix": ("remix", "ریمیکس"),
    "remaster": ("remaster", "remastered"),
    "acoustic": ("acoustic", "آکوستیک"),
    "instrumental": ("instrumental", "بی کلام", "بیکلام"),
}


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _version(title: str, album: str) -> str:
    combined = _normalized(f"{title} {album}")
    for name, markers in _VERSION_MARKERS.items():
        if any(marker in combined for marker in markers):
            return name
    return "studio"


def _group_id(artist: str, title: str) -> str:
    digest = hashlib.sha256(
        f"{_normalized(artist)}\0{_normalized(title)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"versions-{digest}"


def _safe_filename(recording_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", recording_id).strip("-.")
    if not value:
        value = hashlib.sha256(recording_id.encode("utf-8")).hexdigest()[:24]
    return value + ".mp3"


def _read_rows(db_path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"recordings", "audio_files", "external_ids"}
        if not required.issubset(tables):
            raise ValueError("fingerprint database does not contain the V2 identity tables")
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    r.id AS recording_id,
                    r.artist,
                    r.title,
                    COALESCE(r.album, '') AS album,
                    r.confidence,
                    af.id AS audio_file_id,
                    af.source_path,
                    af.duration_seconds
                FROM recordings r
                JOIN audio_files af ON af.recording_id = r.id
                WHERE r.status = 'active'
                  AND af.source_path IS NOT NULL
                  AND af.duration_seconds IS NOT NULL
                ORDER BY r.confidence DESC, r.id, af.id
                """
            )
        ]
        identifiers: dict[str, dict[str, str]] = {}
        for row in connection.execute(
            """
            SELECT recording_id, provider, external_id
            FROM external_ids
            WHERE entity_type = 'recording'
            ORDER BY recording_id, provider, id
            """
        ):
            recording_id = str(row["recording_id"])
            provider = str(row["provider"] or "").casefold().strip()
            external_id = str(row["external_id"] or "").strip()
            if provider and external_id:
                identifiers.setdefault(recording_id, {}).setdefault(provider, external_id)
        return rows, identifiers
    finally:
        connection.close()


def bootstrap_manifest(
    *,
    db_path: Path,
    corpus_root: Path,
    output_manifest: Path,
    limit: int = 100,
    minimum_duration_seconds: float = 20.0,
    validation_percent: int = 80,
    seed: int = 20260718,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be greater than zero")
    if not 1 <= validation_percent <= 99:
        raise ValueError("validation_percent must be between 1 and 99")
    corpus_root = Path(corpus_root).resolve()
    references_root = corpus_root / "references" / "local"
    references_root.mkdir(parents=True, exist_ok=True)
    rows, external_ids = _read_rows(Path(db_path))

    selected: list[dict[str, Any]] = []
    seen_recordings: set[str] = set()
    for row in rows:
        recording_id = str(row.get("recording_id") or "")
        if not recording_id or recording_id in seen_recordings:
            continue
        source = Path(str(row.get("source_path") or "")).expanduser().resolve()
        duration = float(row.get("duration_seconds") or 0.0)
        if (
            not source.is_file()
            or source.suffix.casefold() != ".mp3"
            or duration < minimum_duration_seconds
        ):
            continue
        seen_recordings.add(recording_id)
        selected.append({**row, "source": source, "duration": duration})
        if len(selected) >= limit:
            break
    if not selected:
        raise RuntimeError("no usable MP3 references were found in the fingerprint database")

    identity_counts: dict[tuple[str, str], int] = {}
    for row in selected:
        key = (_normalized(row["artist"]), _normalized(row["title"]))
        identity_counts[key] = identity_counts.get(key, 0) + 1

    references: list[dict[str, Any]] = []
    copied_bytes = 0
    for index, row in enumerate(selected):
        recording_id = str(row["recording_id"])
        source = Path(row["source"])
        destination = references_root / _safe_filename(recording_id)
        shutil.copy2(source, destination)
        copied_bytes += destination.stat().st_size
        artist = " ".join(str(row["artist"] or "").split())
        title = " ".join(str(row["title"] or "").split())
        album = " ".join(str(row["album"] or "").split())
        identity_key = (_normalized(artist), _normalized(title))
        identifiers = {"avachin": recording_id}
        for provider, external_id in external_ids.get(recording_id, {}).items():
            if provider in {"isrc", "musicbrainz", "spotify", "apple"}:
                identifiers[provider] = external_id
        references.append(
            {
                "recording_id": recording_id,
                "path": destination.relative_to(corpus_root).as_posix(),
                "title": title,
                "artist": artist,
                "duration_seconds": round(float(row["duration"]), 3),
                "split": (
                    "validation"
                    if (index * 100 // len(selected)) < validation_percent
                    else "test"
                ),
                "version": _version(title, album),
                "hard_negative_group": (
                    _group_id(artist, title)
                    if identity_counts[identity_key] > 1
                    else ""
                ),
                "identifiers": identifiers,
            }
        )

    payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "name": "Avachin local fingerprint validation corpus",
        "seed": int(seed),
        "bootstrap": {
            "source_db": str(Path(db_path).resolve()),
            "references": len(references),
            "copied_bytes": copied_bytes,
            "review_required": True,
            "note": (
                "Verify artist/title/version and hard-negative groups before "
                "using this manifest for release thresholds."
            ),
        },
        "references": references,
        "transforms": [
            {"transform_id": "clean", "kind": "identity"},
            {
                "transform_id": "clip-middle-5",
                "kind": "clip",
                "parameters": {"duration_seconds": 5, "position": "middle"},
            },
            {
                "transform_id": "clip-middle-10",
                "kind": "clip",
                "parameters": {"duration_seconds": 10, "position": "middle"},
            },
            {
                "transform_id": "clip-middle-15",
                "kind": "clip",
                "parameters": {"duration_seconds": 15, "position": "middle"},
            },
            {
                "transform_id": "bitrate-64",
                "kind": "bitrate",
                "parameters": {"bitrate_kbps": 64},
            },
            {
                "transform_id": "bitrate-128",
                "kind": "bitrate",
                "parameters": {"bitrate_kbps": 128},
            },
            {
                "transform_id": "bitrate-320",
                "kind": "bitrate",
                "parameters": {"bitrate_kbps": 320},
            },
            {
                "transform_id": "trim-head-tail",
                "kind": "trim",
                "parameters": {"head_seconds": 8, "tail_seconds": 8},
            },
            {
                "transform_id": "leading-silence-2",
                "kind": "silence",
                "parameters": {"leading_seconds": 2},
            },
            {
                "transform_id": "white-noise",
                "kind": "noise",
                "parameters": {"color": "white", "amplitude": 0.015},
            },
            {
                "transform_id": "volume-minus-6db",
                "kind": "volume",
                "parameters": {"decibels": -6},
            },
        ],
    }
    output_manifest = Path(output_manifest).resolve()
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "bootstrapped",
        "manifest": str(output_manifest),
        "references": len(references),
        "copied_bytes": copied_bytes,
        "review_required": True,
    }
