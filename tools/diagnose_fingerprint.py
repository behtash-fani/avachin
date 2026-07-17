#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose AcoustID fingerprint recognition for one audio file.

This tool does not rename, move, or modify files. It only shows whether the
current Avachin setup can fingerprint a problematic unknown track and whether
AcoustID/MusicBrainz returns a usable candidate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_launcher as launcher  # noqa: E402

app = launcher.app


def _safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return text if text else "-"


def _print_tags(audio: Any) -> None:
    tags = audio.tags
    print("Local tags:")
    for name in (
        "title",
        "artist",
        "albumartist",
        "album",
        "date",
        "tracknumber",
        "isrc",
        "musicbrainz_trackid",
    ):
        print(f"  {name}: {_safe(getattr(tags, name, None))}")
    print(f"  duration: {_safe(round(audio.duration_seconds or 0, 2))} seconds")
    print(f"  bitrate: {_safe(round((audio.bitrate_bps or 0) / 1000) if audio.bitrate_bps else None)} kbps")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check one file with Avachin AcoustID recognition.")
    parser.add_argument("--file", type=Path, help="Path to one MP3 file")
    args = parser.parse_args()

    source = args.file
    if source is None:
        entered = input("MP3 file path: ").strip().strip('"')
        source = Path(entered) if entered else None
    if source is None or not source.exists() or not source.is_file():
        print("A valid MP3 file was not provided.", file=sys.stderr)
        return 2

    config = app.load_config(PROJECT_ROOT)
    app_dir = app.app_data_dir()
    cache = app.Cache(app_dir / "catalog_cache.sqlite3")
    client = app.CatalogClient(
        cache=cache,
        musicbrainz_contact=str(config.get("musicbrainz_contact", "")),
        spotify_client_id=str(config.get("spotify_client_id", "")),
        spotify_client_secret=str(config.get("spotify_client_secret", "")),
        apple_country=str(config.get("apple_country", "US")),
    )
    client.enable_musicbrainz_provider = app.provider_enabled(config, "musicbrainz", True)
    client.enable_apple_provider = app.provider_enabled(config, "apple_itunes", True)
    client.enable_spotify_provider = app.provider_enabled(config, "spotify", False)
    client.enable_acoustid_provider = app.provider_enabled(config, "acoustid", True)

    fpcalc_path = app.find_fpcalc(PROJECT_ROOT)
    api_key = str(config.get("acoustid_api_key") or "").strip()

    print(f"Avachin fingerprint diagnostic")
    print(f"File: {source}")
    print(f"fpcalc: {fpcalc_path if fpcalc_path else 'NOT FOUND'}")
    print(f"AcoustID key: {'FOUND' if api_key else 'NOT FOUND'}")
    print(f"AcoustID provider: {'ON' if client.enable_acoustid_provider else 'OFF'}")
    print()

    audio = app.read_mp3(source)
    _print_tags(audio)
    print()

    if fpcalc_path is None:
        print("Result: fingerprint check cannot run because fpcalc was not found.")
        return 2
    if not api_key:
        print("Result: fingerprint check cannot run because AcoustID key is not active.")
        print("Run: .\\scripts\\windows\\set_acoustid_key.bat")
        return 2
    if not client.enable_acoustid_provider:
        print("Result: fingerprint check cannot run because online_providers.acoustid is OFF.")
        return 2

    print("Running fpcalc + AcoustID lookup...")
    candidate, errors = app.identify_by_fingerprint(source, fpcalc_path, client, config)
    cache.close()

    if errors:
        print("Errors / warnings:")
        for error in errors:
            print(f"  - {error}")
        print()

    if candidate is None:
        print("Result: no trusted AcoustID candidate was returned.")
        print("This usually means the recording is not covered by AcoustID/MusicBrainz, or the score is below the trust threshold.")
        return 1

    print("Result: MATCH")
    print(f"  source: {candidate.source}")
    print(f"  confidence: {candidate.confidence:.2f}")
    print(f"  title: {_safe(candidate.title)}")
    print(f"  artist: {_safe(candidate.artist)}")
    print(f"  album: {_safe(candidate.album)}")
    print(f"  musicbrainz_recording_id: {_safe(candidate.musicbrainz_recording_id)}")
    print(f"  fingerprint_score: {_safe(candidate.evidence.get('fingerprint_score'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
