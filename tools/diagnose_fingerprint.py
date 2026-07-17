#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnose audio recognition for one audio file.

This tool does not rename, move, or modify files. It shows whether Avachin can
fingerprint a problematic unknown track and whether the local fingerprint
library, AcoustID, or optional audio-recognition fallbacks return a usable
candidate.
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
import tools.local_fingerprint_library as local_fp  # noqa: E402

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


def _print_candidate(candidate: Any) -> None:
    print("Result: MATCH")
    print(f"  source: {candidate.source}")
    print(f"  confidence: {candidate.confidence:.2f}")
    print(f"  title: {_safe(candidate.title)}")
    print(f"  artist: {_safe(candidate.artist)}")
    print(f"  album: {_safe(candidate.album)}")
    print(f"  musicbrainz_recording_id: {_safe(candidate.musicbrainz_recording_id)}")
    print(f"  fingerprint_score: {_safe(candidate.evidence.get('fingerprint_score'))}")
    print(f"  local_fingerprint_score: {_safe(candidate.evidence.get('local_fingerprint_score'))}")
    print(f"  audd_song_link: {_safe(candidate.evidence.get('audd_song_link'))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check one file with Avachin audio recognition.")
    parser.add_argument("--file", type=Path, help="Path to one MP3 file")
    parser.add_argument("--local-only", action="store_true", help="Only check the local fingerprint DB; do not use online APIs")
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
    acoustid_key = str(config.get("acoustid_api_key") or "").strip()
    audd_key = str(config.get("audd_api_token") or "").strip()
    audd_on = app.provider_enabled(config, "audd", False)
    local_on = bool(config.get("local_fingerprint_library_enabled", True))

    print("Avachin fingerprint diagnostic")
    print(f"File: {source}")
    print(f"fpcalc: {fpcalc_path if fpcalc_path else 'NOT FOUND'}")
    print(f"Local fingerprint DB: {'ON' if local_on else 'OFF'}")
    print(f"AcoustID key: {'FOUND' if acoustid_key else 'NOT FOUND'}")
    print(f"AcoustID provider: {'ON' if client.enable_acoustid_provider else 'OFF'}")
    print(f"AudD token: {'FOUND' if audd_key else 'NOT FOUND'}")
    print(f"AudD fallback: {'ON' if audd_on else 'OFF'}")
    print()

    audio = app.read_mp3(source)
    _print_tags(audio)
    print()

    if fpcalc_path is None:
        print("Result: fingerprint check cannot run because fpcalc was not found.")
        return 2

    if local_on:
        print("Checking local fingerprint DB...")
        try:
            local_match = local_fp.match_file(
                source,
                threshold=float(config.get("local_fingerprint_match_threshold", 86.0) or 86.0),
                duration_tolerance_seconds=float(config.get("local_fingerprint_duration_tolerance_seconds", 8.0) or 8.0),
                fpcalc_path=Path(fpcalc_path),
            )
        except Exception as exc:
            print(f"Local fingerprint warning: {exc}")
            local_match = None
        if local_match:
            print("Result: MATCH")
            print("  source: local_fingerprint")
            print(f"  confidence: {float(local_match.get('score') or 0.0):.2f}")
            print(f"  title: {_safe(local_match.get('title'))}")
            print(f"  artist: {_safe(local_match.get('artist'))}")
            print(f"  album: {_safe(local_match.get('album'))}")
            print(f"  local_fingerprint_score: {_safe(local_match.get('fingerprint_score'))}")
            print(f"  duration_diff_seconds: {_safe(local_match.get('duration_diff_seconds'))}")
            cache.close()
            return 0
        print("Local fingerprint DB: no match")
        print()

    if args.local_only:
        cache.close()
        print("Result: no local fingerprint match")
        return 1

    if not acoustid_key and not audd_key:
        print("Result: no audio recognition key is active.")
        print("Run one of these:")
        print("  .\\scripts\\windows\\set_acoustid_key.bat")
        print("  .\\scripts\\windows\\set_audd_key.bat")
        return 2
    if not client.enable_acoustid_provider and not audd_on:
        print("Result: all online audio recognition providers are OFF.")
        return 2

    print("Running fpcalc + AcoustID lookup, then optional fallbacks...")
    candidate, errors = app.identify_by_fingerprint(source, fpcalc_path, client, config)
    cache.close()

    if errors:
        print("Errors / warnings:")
        for error in errors:
            print(f"  - {error}")
        print()

    if candidate is None:
        print("Result: no trusted audio-recognition candidate was returned.")
        print("AcoustID may not cover this recording. Add an AudD token or ACRCloud fallback for broader recognition.")
        return 1

    _print_candidate(candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
