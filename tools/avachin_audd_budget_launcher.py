#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install a conservative local budget around real AudD HTTP requests.

This module is inserted between online auto-learning and the partial-audio
runtime. It wraps only ``requests.post`` calls targeting AudD's recognition
endpoint, so local matches, AcoustID, catalog lookups, and AudD cache hits do
not consume the local counter.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_online_auto_learn_launcher as auto_learn  # noqa: E402
from tools import audd_usage_guard as usage_guard  # noqa: E402

app = auto_learn.app
local_first = auto_learn.local_first
fingerprint_library = auto_learn.fingerprint_library
base_launcher = local_first.launcher
LAUNCHER_VERSION = "12.0"

_ORIGINAL_LOAD_CONFIG = getattr(
    app.load_config,
    "__avachin_original_audd_budget_load_config__",
    app.load_config,
)
_ORIGINAL_POST = getattr(
    app.requests.post,
    "__avachin_original_audd_budget_post__",
    app.requests.post,
)

_BUDGET_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "limit": usage_guard.DEFAULT_LIMIT,
    "budget_id": usage_guard.DEFAULT_BUDGET_ID,
    "db_path": app.app_data_dir() / "provider_usage.sqlite3",
    "fail_closed": True,
}


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _env_or_config(config: dict[str, Any], env_name: str, key: str, default: Any) -> Any:
    env_value = os.environ.get(env_name)
    if env_value is not None and str(env_value).strip() != "":
        return env_value
    return config.get(key, default)


def _capture_budget_settings(config: dict[str, Any]) -> None:
    enabled = _as_bool(
        _env_or_config(
            config,
            "AVACHIN_AUDD_BUDGET_ENABLED",
            "audd_request_budget_enabled",
            True,
        ),
        True,
    )
    limit_count = _as_int(
        _env_or_config(
            config,
            "AVACHIN_AUDD_BUDGET_LIMIT",
            "audd_request_budget_limit",
            usage_guard.DEFAULT_LIMIT,
        ),
        usage_guard.DEFAULT_LIMIT,
    )
    budget_id = str(
        _env_or_config(
            config,
            "AVACHIN_AUDD_BUDGET_ID",
            "audd_request_budget_id",
            usage_guard.DEFAULT_BUDGET_ID,
        )
        or usage_guard.DEFAULT_BUDGET_ID
    ).strip()
    fail_closed = _as_bool(
        _env_or_config(
            config,
            "AVACHIN_AUDD_BUDGET_FAIL_CLOSED",
            "audd_request_budget_fail_closed",
            True,
        ),
        True,
    )
    configured_db = str(config.get("audd_request_budget_db_path") or "").strip()
    db_path = Path(configured_db).expanduser() if configured_db else app.app_data_dir() / "provider_usage.sqlite3"

    _BUDGET_SETTINGS.update(
        {
            "enabled": enabled,
            "limit": limit_count,
            "budget_id": budget_id or usage_guard.DEFAULT_BUDGET_ID,
            "db_path": db_path,
            "fail_closed": fail_closed,
        }
    )


def _load_config_with_audd_budget(script_dir: Path) -> dict[str, Any]:
    config = _ORIGINAL_LOAD_CONFIG(script_dir)
    if not isinstance(config, dict):
        config = {}
    _capture_budget_settings(config)
    return config


def _is_audd_url(url: Any) -> bool:
    return str(url or "").strip().rstrip("/").casefold() == str(
        base_launcher.AUDD_RECOGNIZE_URL
    ).strip().rstrip("/").casefold()


def _request_fingerprint(url: Any, kwargs: dict[str, Any]) -> str:
    filename = ""
    files = kwargs.get("files")
    if isinstance(files, dict):
        payload = files.get("file")
        if isinstance(payload, (tuple, list)) and payload:
            filename = str(payload[0] or "")
    stable = f"{str(url or '').strip()}\x1f{filename}"
    return hashlib.sha256(stable.encode("utf-8", "ignore")).hexdigest()


def _guarded_post(url: Any, *args: Any, **kwargs: Any) -> Any:
    if not _is_audd_url(url):
        return _ORIGINAL_POST(url, *args, **kwargs)

    settings = dict(_BUDGET_SETTINGS)
    if not bool(settings.get("enabled", True)):
        return _ORIGINAL_POST(url, *args, **kwargs)

    try:
        claim = usage_guard.claim_request(
            Path(settings["db_path"]),
            budget_id=str(settings.get("budget_id") or usage_guard.DEFAULT_BUDGET_ID),
            limit_count=int(settings.get("limit") or 0),
            request_fingerprint=_request_fingerprint(url, kwargs),
            note="real AudD HTTP attempt after local/AcoustID/cache miss",
        )
    except Exception as exc:
        if bool(settings.get("fail_closed", True)):
            raise RuntimeError(
                f"AudD local budget ledger failed; request blocked to protect quota: {exc}"
            ) from exc
        return _ORIGINAL_POST(url, *args, **kwargs)

    if not bool(claim.get("allowed")):
        raise RuntimeError(
            "AudD local request budget exhausted "
            f"({claim.get('used', 0)}/{claim.get('limit', 0)} used; "
            "check the AudD dashboard, then reset the local ledger explicitly)"
        )

    return _ORIGINAL_POST(url, *args, **kwargs)


setattr(
    _load_config_with_audd_budget,
    "__avachin_original_audd_budget_load_config__",
    _ORIGINAL_LOAD_CONFIG,
)
setattr(_load_config_with_audd_budget, "__avachin_audd_budget_load_config__", True)
setattr(
    _guarded_post,
    "__avachin_original_audd_budget_post__",
    _ORIGINAL_POST,
)
setattr(_guarded_post, "__avachin_audd_budget_post__", True)


def install_audd_budget_guard() -> None:
    if not getattr(app.load_config, "__avachin_audd_budget_load_config__", False):
        app.load_config = _load_config_with_audd_budget
    if not getattr(app.requests.post, "__avachin_audd_budget_post__", False):
        app.requests.post = _guarded_post
    app.APP_VERSION = LAUNCHER_VERSION


install_audd_budget_guard()


if __name__ == "__main__":
    raise SystemExit(app.main())
