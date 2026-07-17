#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Private-config launcher for Avachin.

This wrapper keeps API keys out of Git-tracked files. It loads the normal
config.json, then overlays config.local.json and environment variables before
calling the main organizer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app


LAUNCHER_VERSION = "11.4"


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
        loaded = json.loads(path.read_text(encoding="utf-8"))
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


def _patched_load_config(script_dir: Path) -> dict[str, Any]:
    config = _ORIGINAL_LOAD_CONFIG(script_dir)
    _merge_config_file(config, script_dir / "config.local.json")
    _apply_private_overrides(config)
    return config


_ORIGINAL_LOAD_CONFIG = app.load_config
app.APP_VERSION = LAUNCHER_VERSION
app.load_config = _patched_load_config


if __name__ == "__main__":
    raise SystemExit(app.main())
