#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local-first runtime entry point for Avachin.

The private-config launcher already installs the AcoustID and AudD fallbacks.
This module moves the local fingerprint database in front of the complete
candidate-resolution pipeline, so a known recording is resolved without any
catalog or recognition request. Local lookup also remains available when the
organizer is started in offline mode.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_launcher as launcher  # noqa: E402

app = launcher.app
LAUNCHER_VERSION = "11.7"

_ORIGINAL_DETERMINE_CANDIDATE = getattr(
    app.determine_candidate,
    "__avachin_original_determine_candidate__",
    app.determine_candidate,
)
_ORIGINAL_ALBUM_IS_TRUSTED = getattr(
    app.album_is_trusted_for_folder,
    "__avachin_original_album_trust__",
    app.album_is_trusted_for_folder,
)


def _normalize_local_candidate(
    candidate: Any,
    audio: Any,
    normalize_persian: bool,
    config: dict[str, Any],
    unknown_artist_folder: str,
) -> Any:
    """Apply the same final cleanup used by the organizer's normal pipeline."""
    candidate.title = app.clean_title(candidate.title, normalize_persian)
    candidate.artist = app.clean_artist_label(
        candidate.artist,
        normalize_persian,
        config,
    )
    source_album = candidate.album or getattr(getattr(audio, "tags", None), "album", None)
    candidate.album = app.clean_album_label(
        source_album,
        candidate.title,
        normalize_persian,
        config,
    )
    if not app.meaningful_artist_label(candidate.artist):
        candidate.artist = (
            str(unknown_artist_folder or "").lstrip("_ ").strip()
            or "Unknown Artist"
        )
    if not app.meaningful_artist_label(candidate.album_artist):
        candidate.album_artist = candidate.artist
    return candidate


def _album_is_trusted_with_local_fingerprint(
    album: str,
    candidate: Any,
    old_tags: Any,
    album_track_count_in_library: int,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Trust a safe album carried by Avachin's own acoustic memory.

    The normal gate still rejects explicit singles and title-like release names.
    This override applies only when the sole remaining objection is that the
    current scan contains fewer than the configured number of album tracks.
    """
    trusted, reason = _ORIGINAL_ALBUM_IS_TRUSTED(
        album,
        candidate,
        old_tags,
        album_track_count_in_library,
        config,
    )
    if trusted or reason != "not-enough-album-evidence":
        return trusted, reason
    if str(getattr(candidate, "source", "") or "").casefold() != "local_fingerprint":
        return trusted, reason
    if not bool(config.get("trust_single_track_local_fingerprint_album", True)):
        return trusted, reason

    evidence = getattr(candidate, "evidence", None)
    if isinstance(evidence, dict):
        evidence["local_fingerprint_album_trusted"] = True
    return True, "trusted-local-fingerprint-album"


setattr(
    _album_is_trusted_with_local_fingerprint,
    "__avachin_original_album_trust__",
    _ORIGINAL_ALBUM_IS_TRUSTED,
)
setattr(
    _album_is_trusted_with_local_fingerprint,
    "__avachin_local_fingerprint_album_trust__",
    True,
)


def _determine_candidate_local_first(
    source: Path,
    audio: Any,
    default_artist: str,
    normalize_persian: bool,
    config: dict[str, Any],
    client: Any,
    min_confidence: float,
    verify_online: bool,
    offline: bool,
    unknown_artist_folder: str,
    fpcalc_path: Path | None = None,
) -> tuple[Any, list[str]]:
    """Resolve a trusted local fingerprint before any online/catalog work."""
    local_candidate, local_errors = launcher._identify_by_local_fingerprint(
        source,
        fpcalc_path,
        config,
    )
    if local_candidate is not None:
        local_candidate = _normalize_local_candidate(
            local_candidate,
            audio,
            normalize_persian,
            config,
            unknown_artist_folder,
        )
        local_candidate.evidence["local_first"] = True
        local_candidate.evidence["local_first_offline"] = bool(offline)
        local_candidate.evidence["online_lookup_skipped"] = True
        return local_candidate, local_errors

    candidate, original_errors = _ORIGINAL_DETERMINE_CANDIDATE(
        source,
        audio,
        default_artist,
        normalize_persian,
        config,
        client,
        min_confidence,
        verify_online,
        offline,
        unknown_artist_folder,
        fpcalc_path,
    )
    return candidate, [*local_errors, *original_errors]


setattr(
    _determine_candidate_local_first,
    "__avachin_original_determine_candidate__",
    _ORIGINAL_DETERMINE_CANDIDATE,
)
setattr(_determine_candidate_local_first, "__avachin_local_first__", True)


def install_local_first_runtime() -> None:
    """Install the patches once, including when this module is imported by tests."""
    if not getattr(app.determine_candidate, "__avachin_local_first__", False):
        app.determine_candidate = _determine_candidate_local_first
    if not getattr(
        app.album_is_trusted_for_folder,
        "__avachin_local_fingerprint_album_trust__",
        False,
    ):
        app.album_is_trusted_for_folder = _album_is_trusted_with_local_fingerprint
    app.APP_VERSION = LAUNCHER_VERSION


install_local_first_runtime()


if __name__ == "__main__":
    raise SystemExit(app.main())
