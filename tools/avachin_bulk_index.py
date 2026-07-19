#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical bulk local-fingerprint index entry point.

This public wrapper enables fail-safe repair and artist-name canonicalization
before starting the bulk indexer. Original music files remain read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.artist_alias_runtime import install_artist_alias_hook  # noqa: E402

install_artist_alias_hook()

import tools.avachin_resilient_bulk_index_launcher as runtime  # noqa: E402


def main() -> int:
    return runtime.bulk_index_library.main()


if __name__ == "__main__":
    raise SystemExit(main())
