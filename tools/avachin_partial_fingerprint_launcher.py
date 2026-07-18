#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin v12.1 runtime for resilient local-first recognition.

Full-track Local-first matching stays first. If it misses, the runtime compares
the query against overlapping Schema V3 fingerprint segments before any online
provider is allowed to run. Trusted online learning also indexes segments for
future clip recognition. Real AudD HTTP attempts are protected by a persistent
local request budget. Decoder-damaged audio may be fingerprinted through a
validated temporary repair copy; the original media file is never modified.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_audd_budget_launcher as auto_learn  # noqa: E402
from tools import audio_repair  # noqa: E402
from tools import partial_fingerprint_store as partial_store  # noqa: E402

app = auto_learn.app
base_launcher = auto_learn.local_first.launcher
fingerprint_library = auto_learn.fingerprint_library
LAUNCHER_VERSION = "12.1"

# The shared module is also used by full-track, partial-track, and online
# auto-learning paths, so one idempotent installation covers the complete
# runtime without changing any caller API.
audio_repair.install_fingerprint_repair_runtime(fingerprint_library)

_ORIGINAL_IDENTIFY_BY_LOCAL = getattr(
    base_launcher._identify_by_local_fingerprint,
    "__avachin_original_partial_identify__",
    base_launcher._identify_by_local_fingerprint,
)
_ORIGINAL_LEARN_FILE = getattr(
    fingerprint_library.learn_file,
    "__avachin_original_segment_learn__",
    fingerprint_library.learn_file,
)


def _learn_file_and_index_segments(*args: Any, **kwargs: Any) -> dict[str, Any]:
    result = _ORIGINAL_LEARN_FILE(*args, **kwargs)
    db_path = kwargs.get("db_path")
    conn = partial_store.connect(Path(db_path) if db_path is not None else None)
    try:
        with conn:
            count = partial_store.replace_segments_for_fingerprint(
                conn,
                int(result["id"]),
            )
    finally:
        conn.close()
    result["segments_indexed"] = count
    result["schema_version"] = partial_store.SCHEMA_VERSION
    return result


setattr(
    _learn_file_and_index_segments,
    "__avachin_original_segment_learn__",
    _ORIGINAL_LEARN_FILE,
)
setattr(_learn_file_and_index_segments, "__avachin_segment_learning__", True)


def _identify_by_local_with_partial(
    path: Path,
    fpcalc_path: Any,
    config: dict[str, Any],
) -> tuple[Any | None, list[str]]:
    candidate, errors = _ORIGINAL_IDENTIFY_BY_LOCAL(path, fpcalc_path, config)
    errors = list(errors or [])
    if candidate is not None:
        return candidate, errors

    if not bool(config.get("local_fingerprint_partial_enabled", True)):
        return None, errors

    try:
        match = partial_store.match_file_partial(
            path,
            threshold=float(config.get("local_fingerprint_partial_threshold", 84.0) or 84.0),
            minimum_margin=float(config.get("local_fingerprint_partial_min_margin", 2.0) or 2.0),
            minimum_clip_seconds=float(config.get("local_fingerprint_partial_min_clip_seconds", 12.0) or 12.0),
            fpcalc_path=Path(fpcalc_path) if fpcalc_path else None,
            max_candidates=int(config.get("local_fingerprint_partial_max_candidates", 30000) or 30000),
        )
    except FileNotFoundError:
        return None, errors
    except Exception as exc:
        errors.append(f"Local partial fingerprint: {exc}")
        return None, errors

    if not match:
        return None, errors

    candidate = base_launcher._local_fingerprint_candidate(match)
    if candidate is None:
        return None, errors
    candidate.evidence.update(
        {
            "local_fingerprint_match_mode": "segment",
            "local_fingerprint_segment_id": match.get("id"),
            "local_fingerprint_recording_id": match.get("recording_id"),
            "local_fingerprint_segment_start_seconds": match.get("segment_start_seconds"),
            "local_fingerprint_segment_end_seconds": match.get("segment_end_seconds"),
            "local_fingerprint_runner_up_margin": match.get("runner_up_margin"),
            "local_fingerprint_schema_version": partial_store.SCHEMA_VERSION,
            "partial_audio_match": True,
        }
    )
    return candidate, errors


setattr(
    _identify_by_local_with_partial,
    "__avachin_original_partial_identify__",
    _ORIGINAL_IDENTIFY_BY_LOCAL,
)
setattr(_identify_by_local_with_partial, "__avachin_partial_fingerprint__", True)


def install_partial_fingerprint_runtime() -> None:
    if not getattr(fingerprint_library.learn_file, "__avachin_segment_learning__", False):
        fingerprint_library.learn_file = _learn_file_and_index_segments
    if not getattr(base_launcher._identify_by_local_fingerprint, "__avachin_partial_fingerprint__", False):
        base_launcher._identify_by_local_fingerprint = _identify_by_local_with_partial
    app.APP_VERSION = LAUNCHER_VERSION


install_partial_fingerprint_runtime()


if __name__ == "__main__":
    raise SystemExit(app.main())
