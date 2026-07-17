#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local-first runtime with guarded online-to-local acoustic learning.

The normal resolver remains local-first. When the local database misses and a
trusted online result resolves an uncertain input, this wrapper stores the
file's Chromaprint in Schema V2. Subsequent runs can then recognize the same
recording locally without repeating the online lookup.

Learning is deliberately conservative:

- local, tag-only, cleanup, and registry candidates are never learned here;
- the original file must have an uncertain identity by default;
- AcoustID/AudD results must meet the acoustic confidence threshold;
- catalog-only results require very high confidence plus provider consensus;
- learning failures are warnings and never stop Preview or Apply.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_local_first_launcher as local_first  # noqa: E402
from tools import local_fingerprint_library as fingerprint_library  # noqa: E402

app = local_first.app
LAUNCHER_VERSION = "11.8"

ACOUSTIC_ONLINE_SOURCES = {"acoustid", "audd"}
CATALOG_ONLINE_SOURCES = {"musicbrainz", "apple", "spotify", "deezer"}
DEFAULT_ALLOWED_SOURCES = ACOUSTIC_ONLINE_SOURCES | CATALOG_ONLINE_SOURCES
PLACEHOLDER_VALUES = {
    "",
    "-",
    "na",
    "n/a",
    "none",
    "unknown",
    "unknown artist",
    "unknown title",
    "untitled",
    "no title",
    "track",
    "track 1",
}

_ORIGINAL_DETERMINE_CANDIDATE = getattr(
    app.determine_candidate,
    "__avachin_original_online_auto_learn__",
    app.determine_candidate,
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _key(value: Any) -> str:
    return _text(value).casefold()


def _configured_sources(config: dict[str, Any]) -> set[str]:
    raw = config.get("online_auto_learn_allowed_sources")
    if isinstance(raw, str):
        values: Iterable[Any] = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        return set(DEFAULT_ALLOWED_SOURCES)
    selected = {_key(item) for item in values if _key(item)}
    return selected or set(DEFAULT_ALLOWED_SOURCES)


def _is_placeholder(value: Any) -> bool:
    text = _key(value)
    if text in PLACEHOLDER_VALUES:
        return True
    return any(
        marker in text
        for marker in (
            "unknown artist",
            "unknown title",
            "untitled",
        )
    )


def _candidate_identity_is_valid(candidate: Any) -> bool:
    title = _text(getattr(candidate, "title", ""))
    artist = _text(getattr(candidate, "artist", ""))
    if _is_placeholder(title) or _is_placeholder(artist):
        return False
    return bool(title and artist and app.meaningful_artist_label(artist))


def input_identity_is_uncertain(source: Path, audio: Any) -> bool:
    """Trust complete valid tags even when the physical filename is poor."""
    del source  # Filename hints must not override a complete reliable tag pair.
    tags = getattr(audio, "tags", None)
    tag_title = getattr(tags, "title", "") if tags is not None else ""
    tag_artist = ""
    if tags is not None:
        tag_artist = getattr(tags, "artist", "") or getattr(tags, "albumartist", "")
    return _is_placeholder(tag_title) or _is_placeholder(tag_artist)


def _online_consensus_sources(candidate: Any) -> set[str]:
    sources = {_key(getattr(candidate, "source", ""))}
    for item in getattr(candidate, "consensus_sources", None) or []:
        sources.add(_key(item))
    return {item for item in sources if item in DEFAULT_ALLOWED_SOURCES}


def auto_learn_decision(
    source: Path,
    audio: Any,
    candidate: Any,
    config: dict[str, Any],
    *,
    offline: bool,
    fpcalc_path: Path | None,
) -> tuple[bool, str]:
    """Return a stable eligibility decision and a diagnostic reason."""
    if not bool(config.get("online_auto_learn_enabled", True)):
        return False, "disabled"
    if offline:
        return False, "offline"
    if fpcalc_path is None:
        return False, "fpcalc-unavailable"
    if candidate is None:
        return False, "no-candidate"

    source_key = _key(getattr(candidate, "source", ""))
    if source_key not in _configured_sources(config):
        return False, f"source-not-allowed:{source_key or 'unknown'}"
    if source_key not in DEFAULT_ALLOWED_SOURCES:
        return False, f"not-online-source:{source_key or 'unknown'}"
    if not _candidate_identity_is_valid(candidate):
        return False, "invalid-candidate-identity"

    require_uncertain = bool(config.get("online_auto_learn_require_uncertain_input", True))
    if require_uncertain and not input_identity_is_uncertain(source, audio):
        return False, "input-identity-already-reliable"

    confidence = float(getattr(candidate, "confidence", 0.0) or 0.0)
    if source_key in ACOUSTIC_ONLINE_SOURCES:
        minimum = float(config.get("online_auto_learn_acoustic_min_confidence", 94.0) or 94.0)
        if confidence < minimum:
            return False, f"acoustic-confidence-below:{minimum:g}"
        return True, "trusted-acoustic-result"

    minimum = float(config.get("online_auto_learn_catalog_min_confidence", 99.0) or 99.0)
    if confidence < minimum:
        return False, f"catalog-confidence-below:{minimum:g}"
    consensus = _online_consensus_sources(candidate)
    required_consensus = int(config.get("online_auto_learn_catalog_min_consensus_sources", 2) or 2)
    if len(consensus) < required_consensus:
        return False, f"catalog-consensus-below:{required_consensus}"
    return True, "trusted-catalog-consensus"


def candidate_external_ids(candidate: Any) -> list[tuple[str, str, str]]:
    """Extract recording-level IDs that are safe to attach to one recording."""
    values = [
        ("musicbrainz", "recording", getattr(candidate, "musicbrainz_recording_id", None)),
        ("spotify", "track", getattr(candidate, "spotify_track_id", None)),
        ("apple", "track", getattr(candidate, "apple_track_id", None)),
        ("isrc", "recording", getattr(candidate, "isrc", None)),
    ]
    result: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for provider, entity_type, value in values:
        external_id = _text(value)
        if not external_id:
            continue
        item = (provider, entity_type, external_id)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _determine_candidate_with_online_auto_learn(
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
    candidate, errors = _ORIGINAL_DETERMINE_CANDIDATE(
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
    errors = list(errors or [])

    eligible, reason = auto_learn_decision(
        source,
        audio,
        candidate,
        config,
        offline=offline,
        fpcalc_path=fpcalc_path,
    )
    if candidate is not None:
        candidate.evidence["online_auto_learn_status"] = "eligible" if eligible else "skipped"
        candidate.evidence["online_auto_learn_reason"] = reason
    if not eligible:
        return candidate, errors

    try:
        learned = fingerprint_library.learn_file(
            source,
            artist=_text(candidate.artist),
            title=_text(candidate.title),
            album=_text(candidate.album),
            source=f"online:{_key(candidate.source)}",
            confidence=float(candidate.confidence),
            fpcalc_path=Path(fpcalc_path) if fpcalc_path else None,
            external_ids=candidate_external_ids(candidate),
        )
    except Exception as exc:
        warning = f"Online auto-learn warning: {exc}"
        errors.append(warning)
        candidate.evidence["online_auto_learn_status"] = "failed"
        candidate.evidence["online_auto_learn_error"] = str(exc)
        return candidate, errors

    candidate.evidence["online_auto_learn_status"] = "learned"
    candidate.evidence["online_auto_learn_recording_id"] = learned.get("recording_id")
    candidate.evidence["online_auto_learn_fingerprint_id"] = learned.get("id")
    candidate.evidence["online_auto_learn_schema_version"] = learned.get("schema_version")
    candidate.evidence["online_auto_learn_external_ids_added"] = learned.get("external_ids_added", 0)
    print(
        "  [auto-learn] "
        f"{source.name} -> {candidate.title} / {candidate.artist} "
        f"[{candidate.source} {float(candidate.confidence):.0f}%]"
    )
    return candidate, errors


setattr(
    _determine_candidate_with_online_auto_learn,
    "__avachin_original_online_auto_learn__",
    _ORIGINAL_DETERMINE_CANDIDATE,
)
setattr(_determine_candidate_with_online_auto_learn, "__avachin_online_auto_learn__", True)


def install_online_auto_learn_runtime() -> None:
    if getattr(app.determine_candidate, "__avachin_online_auto_learn__", False):
        return
    app.APP_VERSION = LAUNCHER_VERSION
    app.determine_candidate = _determine_candidate_with_online_auto_learn


install_online_auto_learn_runtime()


if __name__ == "__main__":
    raise SystemExit(app.main())
