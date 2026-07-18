#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulk-index entry point with fail-safe temporary audio repair enabled."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import audio_repair  # noqa: E402
from tools import local_fingerprint_library as fingerprint_library  # noqa: E402

# Install before bulk_index_library imports/uses the shared fingerprint module.
audio_repair.install_fingerprint_repair_runtime(fingerprint_library)

from tools import bulk_index_library  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(bulk_index_library.main())
