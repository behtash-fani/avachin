#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Command-line access to Avachin Review Center operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.review_controller import ReviewController  # noqa: E402


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Review, correct, learn, revoke, merge and undo Avachin local identities safely."
    )
    root.add_argument("--db", type=Path, help="Optional local fingerprint SQLite path")
    commands = root.add_subparsers(dest="command", required=True)

    queue = commands.add_parser("queue", help="Show REVIEW/REJECT items from a detection report")
    queue.add_argument("--report", type=Path)
    queue.add_argument("--include-safe", action="store_true")

    search = commands.add_parser("search", help="Search local recordings")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--status", default="")
    search.add_argument("--limit", type=int, default=100)

    detail = commands.add_parser("detail", help="Show one recording and its audio files")
    detail.add_argument("recording_id")

    find_path = commands.add_parser("find-path", help="Find the DB association for a local audio path")
    find_path.add_argument("source_path", type=Path)

    reassign = commands.add_parser("reassign", help="Move one audio file to a corrected identity")
    reassign.add_argument("--audio-file-id", type=int, required=True)
    reassign.add_argument("--artist", required=True)
    reassign.add_argument("--title", required=True)
    reassign.add_argument("--album", default="")
    reassign.add_argument("--reviewer", default="local-user")
    reassign.add_argument("--reason", default="manual identity correction")

    learn = commands.add_parser("learn", help="Learn one manually verified REVIEW/REJECT file")
    learn.add_argument("--file", type=Path, required=True)
    learn.add_argument("--artist", required=True)
    learn.add_argument("--title", required=True)
    learn.add_argument("--album", default="")
    learn.add_argument("--reviewer", default="local-user")
    learn.add_argument("--reason", default="human-approved rejected-file identity")

    merge = commands.add_parser("merge", help="Merge a duplicate recording into the correct recording")
    merge.add_argument("--source", required=True)
    merge.add_argument("--target", required=True)
    merge.add_argument("--reviewer", default="local-user")
    merge.add_argument("--reason", default="manual duplicate merge")

    revoke = commands.add_parser("revoke", help="Disable a wrong recording without deleting evidence")
    revoke.add_argument("recording_id")
    revoke.add_argument("--reviewer", default="local-user")
    revoke.add_argument("--reason", default="manual association revoke")

    undo = commands.add_parser("undo", help="Undo the latest or a selected review action")
    undo.add_argument("--action-id", default="")

    history = commands.add_parser("history", help="Show the review audit trail")
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--applied-only", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    controller = ReviewController(db_path=args.db)
    try:
        if args.command == "queue":
            result = controller.queue(args.report, include_safe=bool(args.include_safe))
        elif args.command == "search":
            result = controller.search(args.query, status=args.status, limit=args.limit)
        elif args.command == "detail":
            result = controller.detail(args.recording_id)
        elif args.command == "find-path":
            result = controller.find_path(args.source_path)
        elif args.command == "reassign":
            result = controller.reassign(
                args.audio_file_id,
                artist=args.artist,
                title=args.title,
                album=args.album,
                reviewer=args.reviewer,
                reason=args.reason,
            )
        elif args.command == "learn":
            result = controller.learn_rejected_file(
                args.file,
                artist=args.artist,
                title=args.title,
                album=args.album,
                reviewer=args.reviewer,
                reason=args.reason,
            )
        elif args.command == "merge":
            result = controller.merge(
                args.source,
                args.target,
                reviewer=args.reviewer,
                reason=args.reason,
            )
        elif args.command == "revoke":
            result = controller.revoke(
                args.recording_id,
                reviewer=args.reviewer,
                reason=args.reason,
            )
        elif args.command == "undo":
            result = controller.undo(args.action_id)
        elif args.command == "history":
            result = controller.history(limit=args.limit, include_undone=not args.applied_only)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
    except Exception as exc:
        _print({"status": "failed", "error": str(exc), "command": args.command})
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
