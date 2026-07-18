#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public one-command runner for Avachin's real local benchmark pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_pipeline import run_pipeline  # noqa: E402


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Bootstrap/reuse a local corpus, generate transforms, run offline "
            "Preview, evaluate accuracy, and calibrate zero-false thresholds."
        )
    )
    root.add_argument(
        "--corpus-root",
        default=str(PROJECT_ROOT / "benchmark"),
        help="Local corpus root; real audio under this directory is ignored by Git.",
    )
    root.add_argument(
        "--manifest",
        help="Trusted benchmark manifest. Defaults to <corpus-root>/manifest.json.",
    )
    root.add_argument(
        "--report-root",
        default=str(PROJECT_ROOT / "reports" / "benchmark"),
        help="Parent directory for a unique self-contained benchmark run.",
    )
    root.add_argument("--db", help="Optional local fingerprint SQLite path.")
    root.add_argument(
        "--refresh-corpus",
        action="store_true",
        help="Re-bootstrap and replace the local manifest from the read-only DB.",
    )
    root.add_argument("--limit", type=int, default=100)
    root.add_argument("--minimum-duration", type=float, default=20.0)
    root.add_argument("--validation-percent", type=int, default=80)
    root.add_argument("--seed", type=int, default=20260718)
    root.add_argument("--ffmpeg", help="Optional FFmpeg executable path.")
    root.add_argument(
        "--allow-online",
        action="store_true",
        help=(
            "Allow online providers during Preview. Default is offline so the "
            "benchmark measures local recognition and consumes no provider budget."
        ),
    )
    root.add_argument("--workers", type=int)
    root.add_argument("--min-confidence", type=float)
    root.add_argument("--normalize-persian", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    corpus_root = Path(args.corpus_root).expanduser().resolve()
    manifest = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else corpus_root / "manifest.json"
    )

    def progress(message: str) -> None:
        print(message, flush=True)

    try:
        result = run_pipeline(
            corpus_root=corpus_root,
            manifest_path=manifest,
            report_root=Path(args.report_root),
            db_path=Path(args.db) if args.db else None,
            refresh_corpus=args.refresh_corpus,
            limit=args.limit,
            minimum_duration_seconds=args.minimum_duration,
            validation_percent=args.validation_percent,
            seed=args.seed,
            ffmpeg=args.ffmpeg,
            allow_online=args.allow_online,
            workers=args.workers,
            min_confidence=args.min_confidence,
            normalize_persian=args.normalize_persian,
            progress_listener=progress,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "passed":
        return 0
    if result.get("status") == "gate-failed":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
