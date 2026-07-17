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


LAUNCHER_VERSION = "11.4.2"


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
    """Use compressed POST for AcoustID lookup.

    AcoustID supports GET and POST, but long Chromaprint fingerprints should be
    sent by POST. The API's multi-value ``meta`` parameter also expects values as
    whitespace-separated tokens; using literal plus signs can be encoded as
    ``%2B`` and rejected as a bad request.
    """
    fingerprint_text = str(fingerprint or "")
    params = {
        "client": str(api_key or "").strip(),
        "duration": str(int(duration)),
        "fingerprint": fingerprint_text,
        # Important: spaces are intentional. urllib encodes them as '+', which
        # is what AcoustID expects for multiple meta tokens in form data.
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

            # Retry transient server/rate-limit failures. Do not retry 400s; the
            # response body tells us whether the client key or parameters are bad.
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


def _patched_load_config(script_dir: Path) -> dict[str, Any]:
    config = _ORIGINAL_LOAD_CONFIG(script_dir)
    _merge_config_file(config, script_dir / "config.local.json")
    _apply_private_overrides(config)
    return config


_ORIGINAL_LOAD_CONFIG = app.load_config
app.APP_VERSION = LAUNCHER_VERSION
app.load_config = _patched_load_config
app.CatalogClient.acoustid_lookup = _acoustid_lookup_post


if __name__ == "__main__":
    raise SystemExit(app.main())
