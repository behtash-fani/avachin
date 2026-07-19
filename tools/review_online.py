#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Online identity suggestions for Avachin Review Center.

This module deliberately separates discovery from learning:

- benchmark-generated audio is blocked before any provider call;
- AcoustID is tried first when configured;
- reliable filename/tag hints may use the free catalog providers;
- AudD is the final acoustic fallback and remains protected by the existing
  persistent request-budget guard;
- a successful lookup only returns a suggestion. The local acoustic database is
  changed later, and only through the audited human-confirmation action.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from tools import review_service
from tools.review_controller import ReviewController

# Import the canonical runtime so private config overlays, AcoustID POST support,
# AudD request budgeting, audio repair and partial-fingerprint behavior are all
# installed exactly once. We still call the lower-level provider functions below
# so the normal online auto-learn wrapper is never entered.
import tools.avachin_partial_fingerprint_launcher as runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = runtime.app
base_launcher = runtime.base_launcher

_PLACEHOLDERS = {
    "",
    "-",
    "na",
    "n/a",
    "none",
    "unknown",
    "unknown artist",
    "unknown title",
    "untitled",
    "track",
    "track 1",
    "sample",
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _key(value: Any) -> str:
    return _text(value).casefold()


def _path_parts(value: Path | str) -> list[str]:
    try:
        path = Path(value).expanduser().resolve()
    except Exception:
        path = Path(str(value or ""))
    return [part.casefold() for part in path.parts]


def is_benchmark_report(path: Path | str) -> bool:
    parts = _path_parts(path)
    return "benchmark" in parts and "reports" in parts


def is_benchmark_sample(path: Path | str) -> bool:
    parts = _path_parts(path)
    return "benchmark" in parts and "generated" in parts


def _default_report_roots() -> list[Path]:
    roots = [PROJECT_ROOT / "reports", app.app_data_dir() / "reports"]
    output: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.expanduser().resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(root)
    return output


def latest_real_detection_report(roots: Iterable[Path | str] | None = None) -> Path | None:
    """Return the newest non-benchmark DetectionResult report."""
    candidates: list[Path] = []
    for raw_root in roots or _default_report_roots():
        root = Path(raw_root).expanduser().resolve()
        if not root.exists():
            continue
        for filename in ("detection-report.json", "detection_report.json"):
            for item in root.rglob(filename):
                if item.is_file() and not is_benchmark_report(item):
                    candidates.append(item)
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    if candidate is None:
        return {}
    if is_dataclass(candidate):
        return dict(asdict(candidate))
    if isinstance(candidate, dict):
        return dict(candidate)
    fields = (
        "source",
        "title",
        "artist",
        "album",
        "album_artist",
        "date",
        "tracknumber",
        "discnumber",
        "genre",
        "isrc",
        "duration_ms",
        "confidence",
        "title_similarity",
        "artist_similarity",
        "duration_similarity",
        "consensus_sources",
        "musicbrainz_recording_id",
        "musicbrainz_artist_ids",
        "musicbrainz_release_id",
        "spotify_track_id",
        "apple_track_id",
        "evidence",
    )
    return {field: getattr(candidate, field, None) for field in fields}


def _suggestion(
    candidate: Any,
    *,
    path: Path,
    errors: list[str],
    attempted: list[str],
) -> dict[str, Any]:
    payload = _candidate_payload(candidate)
    if not payload:
        return {
            "status": "not-found",
            "source_path": str(path),
            "attempted_providers": attempted,
            "errors": errors,
            "database_changed": False,
            "learned": False,
            "requires_human_confirmation": True,
        }
    return {
        "status": "suggested",
        "source_path": str(path),
        "provider": _text(payload.get("source")),
        "artist": _text(payload.get("artist")),
        "title": _text(payload.get("title")),
        "album": _text(payload.get("album")),
        "confidence": float(payload.get("confidence") or 0.0),
        "consensus_sources": list(payload.get("consensus_sources") or []),
        "isrc": _text(payload.get("isrc")),
        "musicbrainz_recording_id": _text(payload.get("musicbrainz_recording_id")),
        "spotify_track_id": _text(payload.get("spotify_track_id")),
        "apple_track_id": _text(payload.get("apple_track_id")),
        "evidence": dict(payload.get("evidence") or {}),
        "attempted_providers": attempted,
        "errors": errors,
        "database_changed": False,
        "learned": False,
        "requires_human_confirmation": True,
    }


def _reliable_catalog_seeds(path: Path, audio: Any, config: dict[str, Any]) -> list[Any]:
    seeds = app.generate_seeds(
        path,
        audio.tags,
        str(config.get("default_artist") or "") or None,
        False,
        config,
    )
    output: list[Any] = []
    for seed in seeds:
        title = _key(getattr(seed, "title", ""))
        artist = _key(getattr(seed, "artist", ""))
        if not title or not artist:
            continue
        if title in _PLACEHOLDERS or artist in _PLACEHOLDERS:
            continue
        if title.startswith("sample-") or artist.startswith("sample-"):
            continue
        if not app.meaningful_artist_label(str(getattr(seed, "artist", "") or "")):
            continue
        output.append(seed)
    return output


def _catalog_client(config: dict[str, Any]) -> tuple[Any, Any]:
    cache = app.Cache(app.app_data_dir() / "catalog_cache.sqlite3")
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
    client.spotify_market = str(config.get("spotify_market", "") or "")
    client.spotify_cache_days = int(config.get("spotify_cache_days", 30) or 30)
    client.spotify_search_limit = int(config.get("spotify_search_limit", 10) or 10)
    return cache, client


def resolve_online_identity(source_path: Path | str) -> dict[str, Any]:
    """Return one online suggestion without modifying local acoustic memory."""
    path = Path(source_path).expanduser().resolve()
    if is_benchmark_sample(path):
        raise ValueError(
            "Benchmark-generated samples are synthetic test artifacts. "
            "Online lookup is blocked to avoid wasting provider quota."
        )
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() != ".mp3":
        raise ValueError("online identity lookup currently supports MP3 files only")

    config = app.load_config(PROJECT_ROOT)
    cache, client = _catalog_client(config)
    errors: list[str] = []
    attempted: list[str] = []
    try:
        audio = app.read_mp3(path)
        fpcalc_path = app.find_fpcalc(PROJECT_ROOT)

        # 1) Free acoustic recognition first. Use the original AcoustID layer so
        # local DB matches cannot echo a possibly wrong association back to Review.
        attempted.append("acoustid")
        candidate, provider_errors = base_launcher._ORIGINAL_IDENTIFY_BY_FINGERPRINT(
            path,
            fpcalc_path,
            client,
            config,
        )
        errors.extend(list(provider_errors or []))
        if candidate is not None:
            return _suggestion(candidate, path=path, errors=errors, attempted=attempted)

        # 2) Free catalog verification only when tags/folder/filename produced a
        # meaningful Artist+Title seed. Unknown/sample placeholders are skipped.
        seeds = _reliable_catalog_seeds(path, audio, config)
        if seeds:
            attempted.append("catalog")
            candidate, provider_errors = app.identify_online(audio, seeds, client, config)
            errors.extend(list(provider_errors or []))
            if candidate is not None and float(getattr(candidate, "confidence", 0.0) or 0.0) >= 80.0:
                return _suggestion(candidate, path=path, errors=errors, attempted=attempted)

        # 3) AudD is last because it may consume one guarded request. Cache hits do
        # not consume the counter; the existing fail-closed budget wrapper remains
        # the sole authority around a real outbound request.
        attempted.append("audd")
        candidate, provider_errors = base_launcher._identify_by_audd(path, config)
        errors.extend(list(provider_errors or []))
        return _suggestion(candidate, path=path, errors=errors, attempted=attempted)
    finally:
        try:
            cache.close()
        except Exception:
            pass


class OnlineReviewController(ReviewController):
    """Review facade with non-mutating online suggestions."""

    def queue(self, report_path: Path | str | None = None, *, include_safe: bool = False) -> dict[str, Any]:
        explicit = Path(report_path).expanduser().resolve() if report_path else None
        path = explicit or latest_real_detection_report()
        result = review_service.load_review_queue(path, include_safe=include_safe)
        report = str(result.get("report_path") or "")
        result["report_kind"] = "benchmark" if report and is_benchmark_report(report) else "real"
        for item in result.get("items") or []:
            source = str(item.get("source_path") or "")
            benchmark = is_benchmark_sample(source)
            exists = bool(source and Path(source).expanduser().is_file())
            item["benchmark_sample"] = benchmark
            item["online_lookup_allowed"] = bool(exists and not benchmark)
        return result

    def identify_online(self, source_path: Path | str) -> dict[str, Any]:
        return resolve_online_identity(source_path)
