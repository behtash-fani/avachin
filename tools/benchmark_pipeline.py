#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stable public import facade for Avachin's one-command benchmark pipeline."""

from __future__ import annotations

from typing import Any

from tools import _benchmark_pipeline_core as _core

PIPELINE_SCHEMA_VERSION = _core.PIPELINE_SCHEMA_VERSION
PROJECT_ROOT = _core.PROJECT_ROOT
git_commit = _core.git_commit
sha256_file = _core.sha256_file
timestamp_token = _core.timestamp_token
utc_now = _core.utc_now

_ORIGINAL_SAVE_REPORT = _core._save_report


def _save_report_compat(
    run_dir: Any,
    artifacts: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    return _ORIGINAL_SAVE_REPORT(
        run_dir=run_dir,
        artifacts=artifacts,
        **kwargs,
    )


_core._save_report = _save_report_compat
run_pipeline = _core.run_pipeline

__all__ = [
    "PIPELINE_SCHEMA_VERSION",
    "PROJECT_ROOT",
    "git_commit",
    "run_pipeline",
    "sha256_file",
    "timestamp_token",
    "utc_now",
]
