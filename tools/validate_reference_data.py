#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate local JSON reference data for Smart Music Organizer.

This intentionally has no third-party dependencies so GitHub users can run it
before installing the full project requirements.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = ROOT / "reference_data"


def comparison_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"}))
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def iter_entries(path: Path, key: str) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, dict):
        entries = payload.get(key) or []
    elif isinstance(payload, list):
        entries = payload
    else:
        raise ValueError(f"{path}: root must be an object or list")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: {key} must be a list")
    return [entry for entry in entries if isinstance(entry, dict)]


def main() -> int:
    errors: list[str] = []
    artist_ids: set[str] = set()
    alias_owner: dict[str, str] = {}

    for path in sorted((REFERENCE_ROOT / "artists").glob("*.json")):
        try:
            entries = iter_entries(path, "artists")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for entry in entries:
            artist_id = str(entry.get("id") or "").strip()
            canonical = str(entry.get("canonical_name") or "").strip()
            if not artist_id:
                errors.append(f"{path}: artist without id")
                continue
            if artist_id in artist_ids:
                errors.append(f"{path}: duplicate artist id {artist_id}")
            artist_ids.add(artist_id)
            if not canonical:
                errors.append(f"{path}: {artist_id}: missing canonical_name")
            labels = [canonical, str(entry.get("preferred_folder_name") or ""), str(entry.get("native_name") or "")]
            labels.extend(str(alias) for alias in (entry.get("aliases") or []))
            for label in labels:
                key = comparison_text(label)
                if not key:
                    continue
                previous = alias_owner.get(key)
                if previous and previous != artist_id:
                    errors.append(f"{path}: alias conflict {label!r}: {previous} vs {artist_id}")
                alias_owner[key] = artist_id

    for path in sorted((REFERENCE_ROOT / "tracks").glob("*.json")):
        try:
            entries = iter_entries(path, "tracks")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        seen_track_ids: set[str] = set()
        for entry in entries:
            track_id = str(entry.get("id") or "").strip()
            title = str(entry.get("canonical_title") or entry.get("title") or "").strip()
            if not track_id:
                errors.append(f"{path}: track without id")
                continue
            if track_id in seen_track_ids:
                errors.append(f"{path}: duplicate track id {track_id}")
            seen_track_ids.add(track_id)
            if not title:
                errors.append(f"{path}: {track_id}: missing canonical_title")
            for artist_id in entry.get("artist_ids") or entry.get("artists") or []:
                if str(artist_id) not in artist_ids:
                    errors.append(f"{path}: {track_id}: unknown artist id {artist_id}")
            for alias in entry.get("aliases") or []:
                if not isinstance(alias, dict):
                    errors.append(f"{path}: {track_id}: alias must be an object")
                    continue
                if not str(alias.get("title") or "").strip() or not str(alias.get("artist") or "").strip():
                    errors.append(f"{path}: {track_id}: alias requires title and artist")

    if errors:
        print("Reference data validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Reference data validation OK")
    print(f"Artists: {len(artist_ids)}")
    print(f"Aliases: {len(alias_owner)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
