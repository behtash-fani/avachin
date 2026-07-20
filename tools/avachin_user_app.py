#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persian RTL Material-inspired user application for Avachin."""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.persian_ui_app import PersianMaterialApp
from tools.review_online import latest_real_detection_report
from tools.version import AVACHIN_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Persian RTL Avachin desktop application.")
    parser.add_argument("--folder", default="", help="Optional initial music folder")
    parser.add_argument("--report", default="", help="Optional DetectionResult JSON report")
    parser.add_argument("--check", action="store_true", help="Print the UI contract without opening a window")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print(json.dumps({
            "version": AVACHIN_VERSION,
            "language": "fa",
            "right_to_left": True,
            "theme": "dracula-material",
            "preferred_font": "Vazirmatn",
            "font_fallbacks": ["Vazir", "Vazir UI", "Tahoma", "Segoe UI"],
            "preview_only_organizer": True,
            "organizer_apply_exposed": False,
            "review_queue": True,
            "online_suggestions_require_confirmation": True,
            "artist_alias_manager": True,
            "backup_audit_undo": True,
            "latest_real_detection_report": str(latest_real_detection_report() or ""),
        }, ensure_ascii=False, indent=2))
        return 0

    root = tk.Tk()
    PersianMaterialApp(root, initial_folder=args.folder, initial_report=args.report)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
