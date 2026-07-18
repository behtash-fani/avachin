#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistent local request budget for Avachin's AudD fallback.

The ledger counts actual outbound AudD HTTP attempts. Cache hits, local
fingerprint matches, and AcoustID lookups never call this module's claim path.
The budget is intentionally manual: Avachin never assumes whether an AudD
allowance resets monthly, renews on another schedule, or is a one-time credit.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDER = "audd"
DEFAULT_LIMIT = 300
DEFAULT_BUDGET_ID = "manual-300"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path() -> Path:
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / "SmartMusicOrganizer" / "provider_usage.sqlite3"


def _clean_budget_id(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return DEFAULT_BUDGET_ID
    return text[:120]


def _clean_limit(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audd_budget_state (
            budget_id TEXT PRIMARY KEY,
            limit_count INTEGER NOT NULL,
            used_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audd_budget_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            request_fingerprint TEXT,
            note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audd_budget_events_budget
            ON audd_budget_events(budget_id, id);
        """
    )
    conn.commit()
    return conn


def _ensure_state(
    conn: sqlite3.Connection,
    *,
    budget_id: str,
    limit_count: int,
) -> sqlite3.Row:
    timestamp = now_utc()
    conn.execute(
        """
        INSERT INTO audd_budget_state (
            budget_id, limit_count, used_count, created_at, updated_at
        ) VALUES (?, ?, 0, ?, ?)
        ON CONFLICT(budget_id) DO UPDATE SET
            limit_count = excluded.limit_count,
            updated_at = excluded.updated_at
        """,
        (budget_id, limit_count, timestamp, timestamp),
    )
    row = conn.execute(
        "SELECT budget_id, limit_count, used_count, created_at, updated_at "
        "FROM audd_budget_state WHERE budget_id = ?",
        (budget_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("AudD budget state could not be created")
    return row


def _snapshot(row: sqlite3.Row, db_path: Path, *, allowed: bool | None = None) -> dict[str, Any]:
    limit_count = int(row["limit_count"] or 0)
    used_count = int(row["used_count"] or 0)
    result: dict[str, Any] = {
        "provider": PROVIDER,
        "budget_id": str(row["budget_id"]),
        "limit": limit_count,
        "used": used_count,
        "remaining": max(0, limit_count - used_count),
        "exhausted": used_count >= limit_count,
        "db_path": str(db_path),
        "updated_at": str(row["updated_at"] or ""),
    }
    if allowed is not None:
        result["allowed"] = bool(allowed)
    return result


def budget_status(
    db_path: Path | None = None,
    *,
    budget_id: str = DEFAULT_BUDGET_ID,
    limit_count: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else default_db_path()
    clean_id = _clean_budget_id(budget_id)
    clean_limit = _clean_limit(limit_count)
    conn = connect(path)
    try:
        with conn:
            row = _ensure_state(conn, budget_id=clean_id, limit_count=clean_limit)
        return _snapshot(row, path)
    finally:
        conn.close()


def claim_request(
    db_path: Path | None = None,
    *,
    budget_id: str = DEFAULT_BUDGET_ID,
    limit_count: int = DEFAULT_LIMIT,
    request_fingerprint: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Atomically reserve one real outbound AudD request."""
    path = Path(db_path) if db_path is not None else default_db_path()
    clean_id = _clean_budget_id(budget_id)
    clean_limit = _clean_limit(limit_count)
    request_fingerprint = str(request_fingerprint or "").strip()[:128]
    note = " ".join(str(note or "").strip().split())[:300]
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _ensure_state(conn, budget_id=clean_id, limit_count=clean_limit)
        used_count = int(row["used_count"] or 0)
        if used_count >= clean_limit:
            conn.execute(
                """
                INSERT INTO audd_budget_events (
                    budget_id, event_type, request_fingerprint, note, created_at
                ) VALUES (?, 'blocked-exhausted', ?, ?, ?)
                """,
                (clean_id, request_fingerprint or None, note or None, now_utc()),
            )
            conn.commit()
            current = conn.execute(
                "SELECT * FROM audd_budget_state WHERE budget_id = ?",
                (clean_id,),
            ).fetchone()
            assert current is not None
            return _snapshot(current, path, allowed=False)

        timestamp = now_utc()
        conn.execute(
            """
            UPDATE audd_budget_state
            SET used_count = used_count + 1, updated_at = ?
            WHERE budget_id = ?
            """,
            (timestamp, clean_id),
        )
        conn.execute(
            """
            INSERT INTO audd_budget_events (
                budget_id, event_type, request_fingerprint, note, created_at
            ) VALUES (?, 'request-claimed', ?, ?, ?)
            """,
            (clean_id, request_fingerprint or None, note or None, timestamp),
        )
        conn.commit()
        current = conn.execute(
            "SELECT * FROM audd_budget_state WHERE budget_id = ?",
            (clean_id,),
        ).fetchone()
        assert current is not None
        return _snapshot(current, path, allowed=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_budget(
    db_path: Path | None = None,
    *,
    budget_id: str = DEFAULT_BUDGET_ID,
    limit_count: int = DEFAULT_LIMIT,
    confirm: str = "",
) -> dict[str, Any]:
    if str(confirm or "").strip() != "RESET":
        raise RuntimeError('reset refused; pass --confirm RESET after checking the AudD dashboard')
    path = Path(db_path) if db_path is not None else default_db_path()
    clean_id = _clean_budget_id(budget_id)
    clean_limit = _clean_limit(limit_count)
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_state(conn, budget_id=clean_id, limit_count=clean_limit)
        timestamp = now_utc()
        conn.execute(
            """
            UPDATE audd_budget_state
            SET used_count = 0, limit_count = ?, updated_at = ?
            WHERE budget_id = ?
            """,
            (clean_limit, timestamp, clean_id),
        )
        conn.execute(
            """
            INSERT INTO audd_budget_events (
                budget_id, event_type, request_fingerprint, note, created_at
            ) VALUES (?, 'manual-reset', NULL, 'confirmed from dashboard', ?)
            """,
            (clean_id, timestamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM audd_budget_state WHERE budget_id = ?",
            (clean_id,),
        ).fetchone()
        assert row is not None
        return _snapshot(row, path)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def print_status(status: dict[str, Any]) -> None:
    print("AudD local request budget")
    print(f"  budget_id: {status['budget_id']}")
    print(f"  limit: {status['limit']}")
    print(f"  used: {status['used']}")
    print(f"  remaining: {status['remaining']}")
    print(f"  exhausted: {'yes' if status['exhausted'] else 'no'}")
    print(f"  database: {status['db_path']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect or manually reset Avachin's local AudD request budget."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--budget-id", default=DEFAULT_BUDGET_ID)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show used and remaining AudD requests.")
    reset = sub.add_parser("reset", help="Reset local usage only after checking the AudD dashboard.")
    reset.add_argument("--confirm", default="")
    args = parser.parse_args()

    try:
        if args.command == "reset":
            status = reset_budget(
                args.db,
                budget_id=args.budget_id,
                limit_count=args.limit,
                confirm=args.confirm,
            )
        else:
            status = budget_status(
                args.db,
                budget_id=args.budget_id,
                limit_count=args.limit,
            )
        print_status(status)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
