#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical Avachin runtime entry point.

Internal feature launchers remain import-compatible, but user-facing scripts,
future GUI adapters, and packaging should start Avachin through this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tools.avachin_partial_fingerprint_launcher as runtime  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402

app = runtime.app
app.APP_VERSION = AVACHIN_VERSION


def main() -> int:
    return app.main()


if __name__ == "__main__":
    raise SystemExit(main())
