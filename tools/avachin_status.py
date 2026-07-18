#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine-readable runtime status for Avachin desktop and mobile adapters.

The status API never returns provider credentials and opens existing SQLite
files read-only. It is safe to call from a GUI dashboard before starting an
organize, preview, repair, or bulk-index operation.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402
from tools import audio_repair  # noqa: E402
from tools import audd_usage_guard  # noqa: E402
from tools import local_fingerprint_library as local_fp  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402

STATUS_SCHEMA_VERSION = 1


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() not in {
        "",
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def _integer(value: Any, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _read_json_object(path: Path, warnings: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"Could not read {path.name}: {exc}")
        return {}
    if not isinstance(value, dict):
        warnings.append(f"{path.name} must contain a JSON object")
        return {}
    return dict(value)


def load_effective_config(
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict[str, Any], list[str]]:
    """Load tracked and local configuration without returning secrets separately."""
    root = Path(project_root)
    warnings: list[str] = []
    config: dict[str, Any] = {}

    try:
        loaded = app.load_config(root)
    except Exception as exc:
        warnings.append(f"Could not load config.json: {exc}")
        loaded = {}
    if isinstance(loaded, dict):
        config.update(loaded)

    config.update(_read_json_object(root / "config.local.json", warnings))
    return config, warnings


def _env_value(*names: str) -> str:
    for name in names:
        key = str(name or "").strip()
        if not key:
            continue
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def _credential_configured(
    config: dict[str, Any],
    value_key: str,
    env_key_key: str,
    *fallback_env_names: str,
) -> bool:
    if str(config.get(value_key) or "").strip():
        return True
    configured_env = str(config.get(env_key_key) or "").strip()
    return bool(_env_value(configured_env, *fallback_env_names))


def provider_status(config: dict[str, Any]) -> dict[str, Any]:
    providers = config.get("online_providers")
    enabled = dict(providers) if isinstance(providers, dict) else {}

    acoustid_configured = _credential_configured(
        config,
        "acoustid_api_key",
        "acoustid_api_key_env",
        "ACOUSTID_API_KEY",
        "AVACHIN_ACOUSTID_API_KEY",
    )
    audd_configured = _credential_configured(
        config,
        "audd_api_token",
        "audd_api_token_env",
        "AUDD_API_TOKEN",
        "AVACHIN_AUDD_API_TOKEN",
    )
    spotify_configured = bool(
        str(config.get("spotify_client_id") or "").strip()
        and str(config.get("spotify_client_secret") or "").strip()
    ) or bool(
        _env_value("SPOTIFY_CLIENT_ID", "AVACHIN_SPOTIFY_CLIENT_ID")
        and _env_value("SPOTIFY_CLIENT_SECRET", "AVACHIN_SPOTIFY_CLIENT_SECRET")
    )

    result: dict[str, Any] = {}
    for name in (
        "musicbrainz",
        "apple_itunes",
        "acoustid",
        "audd",
        "spotify",
        "deezer",
    ):
        configured = True
        if name == "acoustid":
            configured = acoustid_configured
        elif name == "audd":
            configured = audd_configured
        elif name == "spotify":
            configured = spotify_configured
        result[name] = {
            "enabled": _bool(enabled.get(name), name in {"musicbrainz", "apple_itunes"}),
            "configured": configured,
        }
    return result


def tool_status(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root)

    try:
        fpcalc_value = app.find_fpcalc(root)
        fpcalc_path = Path(fpcalc_value).resolve() if fpcalc_value else None
    except Exception:
        fpcalc_path = None

    try:
        ffmpeg_path = audio_repair.find_ffmpeg(config)
    except Exception:
        ffmpeg_path = None

    return {
        "python": {
            "available": True,
            "version": platform.python_version(),
            "executable": sys.executable,
        },
        "fpcalc": {
            "available": fpcalc_path is not None,
            "path": str(fpcalc_path or ""),
        },
        "ffmpeg": {
            "available": ffmpeg_path is not None,
            "path": str(ffmpeg_path or ""),
        },
    }


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_count(conn: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(conn, table_name):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])


def fingerprint_status(db_path: Path | None = None) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else local_fp.local_db_path()
    result: dict[str, Any] = {
        "db_path": str(path),
        "exists": path.is_file(),
        "schema_version": 0,
        "recordings": 0,
        "audio_files": 0,
        "fingerprints": 0,
        "external_ids": 0,
        "segments": 0,
        "error": "",
    }
    if not path.is_file():
        return result

    try:
        conn = _open_read_only(path)
        try:
            if _table_exists(conn, "schema_meta"):
                row = conn.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is not None:
                    result["schema_version"] = _integer(row[0], 0)
            for table_name, key in (
                ("recordings", "recordings"),
                ("audio_files", "audio_files"),
                ("fingerprints", "fingerprints"),
                ("external_ids", "external_ids"),
                ("fingerprint_segments", "segments"),
            ):
                result[key] = _table_count(conn, table_name)
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def audd_budget_status(
    config: dict[str, Any],
    db_path: Path | None = None,
) -> dict[str, Any]:
    configured_path = str(config.get("audd_request_budget_db_path") or "").strip()
    path = (
        Path(db_path)
        if db_path is not None
        else Path(configured_path).expanduser()
        if configured_path
        else audd_usage_guard.default_db_path()
    )
    budget_id = str(
        config.get("audd_request_budget_id")
        or audd_usage_guard.DEFAULT_BUDGET_ID
    ).strip()
    limit_count = _integer(
        config.get("audd_request_budget_limit"),
        audd_usage_guard.DEFAULT_LIMIT,
    )
    result: dict[str, Any] = {
        "enabled": _bool(config.get("audd_request_budget_enabled"), True),
        "budget_id": budget_id,
        "limit": limit_count,
        "used": 0,
        "remaining": limit_count,
        "exhausted": limit_count <= 0,
        "db_path": str(path),
        "exists": path.is_file(),
        "updated_at": "",
        "error": "",
    }
    if not path.is_file():
        return result

    try:
        conn = _open_read_only(path)
        try:
            if not _table_exists(conn, "audd_budget_state"):
                return result
            row = conn.execute(
                "SELECT limit_count, used_count, updated_at "
                "FROM audd_budget_state WHERE budget_id = ?",
                (budget_id,),
            ).fetchone()
            if row is None:
                return result
            stored_limit = _integer(row["limit_count"], limit_count)
            used = _integer(row["used_count"], 0)
            result.update(
                {
                    "limit": stored_limit,
                    "used": used,
                    "remaining": max(0, stored_limit - used),
                    "exhausted": used >= stored_limit,
                    "updated_at": str(row["updated_at"] or ""),
                }
            )
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def collect_status(
    *,
    project_root: Path = PROJECT_ROOT,
    config_override: dict[str, Any] | None = None,
    fingerprint_db_path: Path | None = None,
    audd_db_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if config_override is None:
        config, warnings = load_effective_config(root)
    else:
        config = dict(config_override)
        warnings = []

    tools = tool_status(root, config)
    fingerprints = fingerprint_status(fingerprint_db_path)
    budget = audd_budget_status(config, audd_db_path)
    providers = provider_status(config)
    repair_enabled = _bool(config.get("audio_repair_enabled"), True)

    if not tools["fpcalc"]["available"]:
        warnings.append("fpcalc is unavailable; acoustic fingerprinting is disabled")
    if repair_enabled and not tools["ffmpeg"]["available"]:
        warnings.append("FFmpeg is unavailable; damaged-audio repair cannot run")
    for name in ("acoustid", "audd", "spotify"):
        item = providers[name]
        if item["enabled"] and not item["configured"]:
            warnings.append(f"{name} is enabled but its credentials are not configured")
    if fingerprints.get("error"):
        warnings.append(f"Fingerprint database: {fingerprints['error']}")
    if budget.get("error"):
        warnings.append(f"AudD budget database: {budget['error']}")

    return {
        "status_schema_version": STATUS_SCHEMA_VERSION,
        "generated_at": now_utc(),
        "version": AVACHIN_VERSION,
        "project_root": str(root),
        "app_data_dir": str(app.app_data_dir()),
        "configuration": {
            "config_exists": (root / "config.json").is_file(),
            "local_config_exists": (root / "config.local.json").is_file(),
            "offline_mode": _bool(config.get("offline"), False),
            "free_first_mode": _bool(config.get("free_first_mode"), True),
            "local_fingerprint_enabled": _bool(
                config.get("local_fingerprint_library_enabled"), True
            ),
            "partial_fingerprint_enabled": _bool(
                config.get("local_fingerprint_partial_enabled"), True
            ),
            "online_auto_learn_enabled": _bool(
                config.get("online_auto_learn_enabled"), True
            ),
            "audio_repair_enabled": repair_enabled,
            "providers": providers,
        },
        "tools": tools,
        "fingerprints": fingerprints,
        "audd_budget": budget,
        "readiness": {
            "organizer": True,
            "acoustic_fingerprinting": bool(tools["fpcalc"]["available"]),
            "audio_repair": bool(not repair_enabled or tools["ffmpeg"]["available"]),
            "local_database": bool(fingerprints["exists"] and not fingerprints["error"]),
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def print_human(status: dict[str, Any]) -> None:
    print(f"Avachin v{status['version']} runtime status")
    print(f"  project: {status['project_root']}")
    print(f"  fpcalc: {'ready' if status['tools']['fpcalc']['available'] else 'missing'}")
    print(f"  ffmpeg: {'ready' if status['tools']['ffmpeg']['available'] else 'missing'}")
    fp = status["fingerprints"]
    print(
        "  fingerprints: "
        f"{fp['fingerprints']} full / {fp['segments']} segments / schema {fp['schema_version']}"
    )
    budget = status["audd_budget"]
    print(
        "  AudD budget: "
        f"{budget['used']}/{budget['limit']} used, {budget['remaining']} remaining"
    )
    warnings = status.get("warnings") or []
    if warnings:
        print("  warnings:")
        for warning in warnings:
            print(f"    - {warning}")
    else:
        print("  warnings: none")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Show secret-free Avachin runtime status for CLI and GUI clients."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of indented JSON",
    )
    args = parser.parse_args()

    status = collect_status()
    if args.json:
        print(
            json.dumps(
                status,
                ensure_ascii=False,
                indent=None if args.compact else 2,
                sort_keys=True,
            )
        )
    else:
        print_human(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
