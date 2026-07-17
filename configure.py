#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path

DEFAULTS = {
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
    "singles_folder": "_Singles",
    "album_subfolders_enabled": True,
    "duplicates_folder": "_Duplicates",
    "collaboration_folder_min_tracks": 3,
    "collaboration_album_min_tracks": 2,
    "folder_granularity": "primary_identity",
    "allow_joint_artist_folders": False,
    "artist_folder_name_style": "snake_case",
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
    "treat_title_named_release_as_single": False,
    "acoustid_api_key": "",
    "fingerprint_identification_enabled": True,
    "fingerprint_when_uncertain": True,
    "fingerprint_min_score": 0.72,
    "max_path_length": 240,
    "progress_every": 25,
    "skip_symlinks": True,
}

path = Path(__file__).resolve().parent / "config.json"

config = dict(DEFAULTS)
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
    except Exception:
        pass

print("Smart Music Organizer v9.2 configuration")
print()
print("This version defaults to Artist/Album folders with deterministic collaboration filenames.")
print("For a mixed library, leave Default Artist blank.")
print("MusicBrainz and Apple work without API keys.")
print("Spotify is optional.")
print()

def ask(label, current=""):
    current_text = str(current)
    suffix = f" [{current_text}]" if current_text else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else current_text

def ask_bool(label, current):
    default_text = "Y" if current else "N"
    value = input(
        f"{label} [Y/N, default {default_text}]: "
    ).strip().lower()
    if not value:
        return bool(current)
    return value in {"y", "yes", "1", "true"}

config["musicbrainz_contact"] = ask(
    "Email or URL for MusicBrainz User-Agent",
    config["musicbrainz_contact"],
)
config["apple_country"] = ask(
    "Apple Store country code",
    config["apple_country"],
).upper()
config["default_artist"] = ask(
    "Default artist hint",
    config["default_artist"],
)
config["spotify_client_id"] = ask(
    "Spotify Client ID (optional)",
    config["spotify_client_id"],
)
config["spotify_client_secret"] = ask(
    "Spotify Client Secret (optional)",
    config["spotify_client_secret"],
)
config["acoustid_api_key"] = ask(
    "AcoustID API key (optional, enables audio fingerprint identification)",
    config["acoustid_api_key"],
)

threshold_text = ask(
    "Minimum online confidence",
    config["min_confidence"],
)
try:
    config["min_confidence"] = float(threshold_text)
except ValueError:
    config["min_confidence"] = 85

config["verify_existing_tags_online"] = ask_bool(
    "Verify already-valid tags online",
    config["verify_existing_tags_online"],
)
config["move_non_mp3"] = ask_bool(
    "Organize non-MP3 files (sidecars stay with albums)",
    config["move_non_mp3"],
)
config["remove_empty_folders"] = ask_bool(
    "Remove empty source folders after organizing",
    config["remove_empty_folders"],
)
config["write_bitrate_tag"] = ask_bool(
    "Write custom BITRATE and BITRATE_MODE ID3 tags",
    config["write_bitrate_tag"],
)
config["album_subfolders_enabled"] = ask_bool(
    "Group tracks by Album/_Singles inside each Artist folder",
    config["album_subfolders_enabled"],
)
config["preserve_sidecars"] = ask_bool(
    "Keep cover/lyrics/cue/playlist files beside their album",
    config["preserve_sidecars"],
)
config["fingerprint_duplicates"] = ask_bool(
    "Use fpcalc to detect audio-equivalent duplicates when available",
    config["fingerprint_duplicates"],
)

path.write_text(
    json.dumps(config, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print()
print(f"Saved: {path}")
print()
print("Advanced alias and collaboration rules can be edited directly")
print("inside config.json. See README.md for examples.")
