#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Private-config launcher for Avachin.

This wrapper keeps API keys out of Git-tracked files. It loads the normal
config.json, then overlays config.local.json and environment variables before
calling the main organizer.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app


LAUNCHER_VERSION = "11.6"
AUDD_RECOGNIZE_URL = "https://api.audd.io/"


def _first_env_value(*names: str) -> str:
    for name in names:
        key = str(name or "").strip()
        if not key:
            continue
        value = os.environ.get(key)
        if value:
            value = value.strip()
            if value:
                return value
    return ""


def _merge_config_file(config: dict[str, Any], path: Path) -> None:
    if not path.exists():
        return
    try:
        # Windows PowerShell 5.1 writes UTF-8 files with a BOM by default.
        # utf-8-sig keeps config.local.json readable even when created by .bat.
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(loaded, dict):
        config.update(loaded)


def _apply_private_overrides(config: dict[str, Any]) -> None:
    config.setdefault("local_fingerprint_library_enabled", True)
    config.setdefault("local_fingerprint_match_threshold", 86.0)
    config.setdefault("local_fingerprint_duration_tolerance_seconds", 8.0)

    acoustid_env = str(config.get("acoustid_api_key_env") or "ACOUSTID_API_KEY")
    acoustid_key = _first_env_value(
        acoustid_env,
        "ACOUSTID_API_KEY",
        "AVACHIN_ACOUSTID_API_KEY",
    )
    if acoustid_key:
        config["acoustid_api_key"] = acoustid_key
        config["fingerprint_identification_enabled"] = True
        config["fingerprint_when_uncertain"] = True
        providers = config.setdefault("online_providers", {})
        if isinstance(providers, dict):
            providers["acoustid"] = True

    audd_env = str(config.get("audd_api_token_env") or "AUDD_API_TOKEN")
    audd_token = _first_env_value(
        audd_env,
        "AUDD_API_TOKEN",
        "AVACHIN_AUDD_API_TOKEN",
    )
    if audd_token:
        config["audd_api_token"] = audd_token
        config["audio_recognition_fallbacks_enabled"] = True
        providers = config.setdefault("online_providers", {})
        if isinstance(providers, dict):
            providers["audd"] = True

    spotify_client_id = _first_env_value(
        "SPOTIFY_CLIENT_ID",
        "AVACHIN_SPOTIFY_CLIENT_ID",
    )
    spotify_client_secret = _first_env_value(
        "SPOTIFY_CLIENT_SECRET",
        "AVACHIN_SPOTIFY_CLIENT_SECRET",
    )
    if spotify_client_id:
        config["spotify_client_id"] = spotify_client_id
    if spotify_client_secret:
        config["spotify_client_secret"] = spotify_client_secret


def _safe_acoustid_error(response: Any) -> str:
    status = getattr(response, "status_code", "?")
    text = ""
    try:
        payload = response.json()
    except Exception:
        try:
            text = str(response.text or "")
        except Exception:
            text = ""
    else:
        if isinstance(payload, dict):
            error = payload.get("error") or payload
            if isinstance(error, dict):
                code = str(error.get("code") or "").strip()
                message = str(error.get("message") or "").strip()
                text = " - ".join(part for part in (code, message) if part)
            else:
                text = str(error)
        else:
            text = str(payload)
    text = " ".join(text.split())[:700]
    return f"HTTP {status}" + (f": {text}" if text else "")


def _acoustid_lookup_post(
    self: Any,
    api_key: str,
    duration: int,
    fingerprint: str,
) -> dict[str, Any]:
    """Use compressed POST for AcoustID lookup."""
    fingerprint_text = str(fingerprint or "")
    params = {
        "client": str(api_key or "").strip(),
        "duration": str(int(duration)),
        "fingerprint": fingerprint_text,
        # Important: spaces are intentional. urllib encodes them as '+', which
        # AcoustID expects for multiple meta tokens in form data.
        "meta": "recordings releasegroups releases tracks compress",
        "format": "json",
    }

    cache_context = dict(params)
    cache_context["fingerprint_sha256"] = app.hashlib.sha256(
        fingerprint_text.encode("utf-8", "ignore")
    ).hexdigest()
    cache_context["fingerprint_length"] = len(fingerprint_text)
    cache_context.pop("fingerprint", None)
    cache_key = self.cache_key(
        "acoustid",
        "POST",
        app.ACOUSTID_LOOKUP_URL,
        cache_context,
    )
    cached = self.cache.get(cache_key, 180)
    if cached is not None:
        return cached

    encoded_body = urllib.parse.urlencode(params).encode("utf-8")
    compressed_body = gzip.compress(encoded_body)
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            headers = dict(self.default_headers)
            headers.update(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Encoding": "gzip",
                }
            )
            response = self.session().post(
                app.ACOUSTID_LOOKUP_URL,
                data=compressed_body,
                headers=headers,
                timeout=self.timeout,
            )

            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt + 1 >= 3:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else float(2 ** attempt)
                except (TypeError, ValueError):
                    delay = float(2 ** attempt)
                app.time.sleep(max(1.0, delay))
                continue

            if response.status_code >= 400:
                raise RuntimeError(_safe_acoustid_error(response))

            payload = response.json()
            if isinstance(payload, dict) and payload.get("status") == "error":
                error = payload.get("error") or {}
                if isinstance(error, dict):
                    message = error.get("message") or error.get("code") or "unknown error"
                else:
                    message = str(error) or "unknown error"
                raise RuntimeError(f"AcoustID API error: {message}")
            if not isinstance(payload, dict):
                raise RuntimeError("AcoustID API returned a non-JSON object")
            self.cache.set(cache_key, payload)
            return payload
        except (app.requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < 3 and not str(exc).startswith("HTTP 400"):
                app.time.sleep(float(2 ** attempt))
                continue
            break

    raise RuntimeError(f"AcoustID POST request failed: {last_error}")


def _audd_token(config: dict[str, Any]) -> str:
    return str(config.get("audd_api_token") or "").strip()


def _audd_cache_key(path: Path, token: str) -> str:
    try:
        audio_sha = app.hash_file(path)
    except Exception:
        audio_sha = app.quick_hash_file(path)
    token_sha = app.hashlib.sha256(token.encode("utf-8", "ignore")).hexdigest()[:16]
    stable = json.dumps(
        {
            "provider": "audd",
            "audio_sha256": audio_sha,
            "token_sha256_prefix": token_sha,
            "api": AUDD_RECOGNIZE_URL,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "audd:" + app.hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _safe_audd_error(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("status") or payload
        if isinstance(error, dict):
            code = str(error.get("error_code") or error.get("code") or "").strip()
            message = str(error.get("error_message") or error.get("message") or "").strip()
            return " - ".join(part for part in (code, message) if part) or str(error)
        return str(error)
    return str(payload)


def _audd_candidate(result: dict[str, Any]) -> app.Candidate | None:
    title = str(result.get("title") or "").strip()
    artist = str(result.get("artist") or "").strip()
    if not title or not artist:
        return None

    spotify = result.get("spotify") if isinstance(result.get("spotify"), dict) else {}
    apple_music = result.get("apple_music") if isinstance(result.get("apple_music"), dict) else {}
    album = (
        str(result.get("album") or "").strip()
        or str((spotify.get("album") or {}).get("name") or "").strip()
        or str(apple_music.get("collectionName") or "").strip()
        or None
    )
    date = (
        str(result.get("release_date") or "").strip()
        or str((spotify.get("album") or {}).get("release_date") or "").strip()
        or str(apple_music.get("releaseDate") or "").split("T", 1)[0].strip()
        or None
    )
    isrc = None
    external_ids = spotify.get("external_ids") if isinstance(spotify.get("external_ids"), dict) else {}
    if external_ids:
        isrc = external_ids.get("isrc")
    if not isrc:
        isrc = apple_music.get("isrc")

    duration_ms = None
    raw_duration = spotify.get("duration_ms") or apple_music.get("trackTimeMillis")
    try:
        if raw_duration is not None:
            duration_ms = int(raw_duration)
    except (TypeError, ValueError):
        duration_ms = None

    spotify_track_id = str(spotify.get("id") or "").strip() or None
    apple_track_id = str(apple_music.get("trackId") or "").strip() or None
    spotify_artists = spotify.get("artists") if isinstance(spotify.get("artists"), list) else []
    artist_entities = [
        str(item.get("name") or "").strip()
        for item in spotify_artists
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ] or [artist]
    artist_keys = [
        f"spotify:{item.get('id')}" if isinstance(item, dict) and item.get("id") else ""
        for item in spotify_artists
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ] or [""]

    return app.Candidate(
        source="audd",
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        date=date,
        isrc=isrc,
        duration_ms=duration_ms,
        spotify_track_id=spotify_track_id,
        apple_track_id=apple_track_id,
        confidence=96.0,
        title_similarity=100.0,
        artist_similarity=100.0,
        duration_similarity=90.0 if duration_ms else 55.0,
        consensus_sources=["audd"],
        evidence={
            "audd_song_link": result.get("song_link"),
            "audd_provider": True,
            "track_artist_entities": artist_entities,
            "track_artist_keys": artist_keys,
            "track_artist_atomic": len(artist_entities) == 1,
            "album_artist_entities": [artist],
            "album_artist_keys": [artist_keys[0] if len(artist_keys) == 1 else ""],
            "album_artist_atomic": True,
            "exact_isrc": bool(isrc),
        },
    )


def _local_fingerprint_candidate(match: dict[str, Any]) -> app.Candidate | None:
    title = str(match.get("title") or "").strip()
    artist = str(match.get("artist") or "").strip()
    if not title or not artist:
        return None
    album = str(match.get("album") or "").strip() or None
    confidence = min(99.0, max(0.0, float(match.get("score") or 0.0)))
    duration_seconds = match.get("query_duration_seconds") or match.get("duration_seconds")
    try:
        duration_ms = int(float(duration_seconds) * 1000) if duration_seconds else None
    except (TypeError, ValueError):
        duration_ms = None

    return app.Candidate(
        source="local_fingerprint",
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        duration_ms=duration_ms,
        confidence=confidence,
        title_similarity=100.0,
        artist_similarity=100.0,
        duration_similarity=float(match.get("duration_score") or 0.0),
        consensus_sources=["local_fingerprint"],
        evidence={
            "local_fingerprint_id": match.get("id"),
            "local_fingerprint_score": match.get("fingerprint_score"),
            "local_fingerprint_duration_diff_seconds": match.get("duration_diff_seconds"),
            "local_fingerprint_source_path": match.get("source_path"),
            "track_artist_entities": [artist],
            "track_artist_keys": ["local_fingerprint"],
            "track_artist_atomic": True,
            "album_artist_entities": [artist],
            "album_artist_keys": ["local_fingerprint"],
            "album_artist_atomic": True,
        },
    )


def _identify_by_local_fingerprint(
    path: Path,
    fpcalc_path: Any,
    config: dict[str, Any],
) -> tuple[app.Candidate | None, list[str]]:
    if not bool(config.get("local_fingerprint_library_enabled", True)):
        return None, []
    try:
        import tools.local_fingerprint_library as local_fp

        match = local_fp.match_file(
            path,
            threshold=float(config.get("local_fingerprint_match_threshold", 86.0) or 86.0),
            duration_tolerance_seconds=float(config.get("local_fingerprint_duration_tolerance_seconds", 8.0) or 8.0),
            fpcalc_path=Path(fpcalc_path) if fpcalc_path else None,
        )
        if not match:
            return None, []
        candidate = _local_fingerprint_candidate(match)
        return candidate, []
    except FileNotFoundError:
        return None, []
    except Exception as exc:
        return None, [f"Local fingerprint: {exc}"]


def _identify_by_audd(path: Path, config: dict[str, Any]) -> tuple[app.Candidate | None, list[str]]:
    if not bool(config.get("audio_recognition_fallbacks_enabled", True)):
        return None, []
    if not app.provider_enabled(config, "audd", False):
        return None, []
    token = _audd_token(config)
    if not token:
        return None, []

    cache_path = app.app_data_dir() / "catalog_cache.sqlite3"
    cache = app.Cache(cache_path)
    cache_key = _audd_cache_key(path, token)
    cached = cache.get(cache_key, int(config.get("audd_cache_days", 30) or 30))
    if isinstance(cached, dict):
        result = cached.get("result") if isinstance(cached.get("result"), dict) else None
        cache.close()
        return (_audd_candidate(result) if result else None), []

    try:
        with path.open("rb") as handle:
            response = app.requests.post(
                AUDD_RECOGNIZE_URL,
                data={
                    "api_token": token,
                    "return": "apple_music,spotify",
                },
                files={"file": (path.name, handle, "audio/mpeg")},
                timeout=float(config.get("audd_request_timeout_seconds", 45) or 45),
            )
        try:
            payload = response.json()
        except ValueError:
            response.raise_for_status()
            return None, ["AudD: non-JSON response"]
        if response.status_code >= 400:
            return None, [f"AudD: HTTP {response.status_code}: {_safe_audd_error(payload)}"]
        if not isinstance(payload, dict):
            return None, ["AudD: invalid response object"]
        if str(payload.get("status") or "").lower() != "success":
            return None, [f"AudD: {_safe_audd_error(payload)}"]
        result = payload.get("result")
        if not isinstance(result, dict):
            cache.set(cache_key, {"result": None})
            return None, []
        cache.set(cache_key, {"result": result})
        return _audd_candidate(result), []
    except Exception as exc:
        return None, [f"AudD: {exc}"]
    finally:
        try:
            cache.close()
        except Exception:
            pass


def _identify_with_audio_fallbacks(
    path: Path,
    fpcalc_path: Any,
    client: Any,
    config: dict[str, Any],
) -> tuple[app.Candidate | None, list[str]]:
    errors: list[str] = []

    local_candidate, local_errors = _identify_by_local_fingerprint(path, fpcalc_path, config)
    errors.extend(local_errors)
    if local_candidate is not None:
        return local_candidate, errors

    candidate, online_errors = _ORIGINAL_IDENTIFY_BY_FINGERPRINT(path, fpcalc_path, client, config)
    errors.extend(online_errors)
    if candidate is not None:
        return candidate, errors

    audd_candidate, audd_errors = _identify_by_audd(path, config)
    errors.extend(audd_errors)
    if audd_candidate is not None:
        audd_candidate.evidence["replaced_candidate_source"] = "acoustid-none"
        return audd_candidate, errors

    return None, errors


def _patched_load_config(script_dir: Path) -> dict[str, Any]:
    config = _ORIGINAL_LOAD_CONFIG(script_dir)
    _merge_config_file(config, script_dir / "config.local.json")
    _apply_private_overrides(config)
    return config


_ORIGINAL_LOAD_CONFIG = app.load_config
_ORIGINAL_IDENTIFY_BY_FINGERPRINT = app.identify_by_fingerprint
app.APP_VERSION = LAUNCHER_VERSION
app.load_config = _patched_load_config
app.CatalogClient.acoustid_lookup = _acoustid_lookup_post
app.identify_by_fingerprint = _identify_with_audio_fallbacks


if __name__ == "__main__":
    raise SystemExit(app.main())
