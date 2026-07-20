#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_FILES = (
    "tools/avachin_user_app.py",
    "tools/persian_ui_app.py",
    "tools/persian_ui_base.py",
    "tools/persian_ui_common.py",
    "tools/persian_ui_home.py",
    "tools/persian_ui_review.py",
    "tools/persian_ui_alias.py",
    "tools/persian_ui_history.py",
)


class PersianUserAppTests(unittest.TestCase):
    def test_headless_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/avachin_user_app.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["version"], "12.15")
        self.assertEqual(payload["language"], "fa")
        self.assertTrue(payload["right_to_left"])
        self.assertEqual(payload["theme"], "dracula-material")
        self.assertEqual(payload["preferred_font"], "Vazirmatn")
        self.assertTrue(payload["preview_only_organizer"])
        self.assertFalse(payload["organizer_apply_exposed"])
        self.assertTrue(payload["review_queue"])
        self.assertTrue(payload["online_suggestions_require_confirmation"])
        self.assertTrue(payload["artist_alias_manager"])
        self.assertTrue(payload["backup_audit_undo"])

    def test_ui_is_persian_material_and_rtl(self) -> None:
        source = "\n".join((PROJECT_ROOT / path).read_text(encoding="utf-8") for path in UI_FILES)
        for text in (
            "خانه و پیش‌نمایش",
            "بررسی آهنگ‌ها",
            "نام‌های هنرمند",
            "تاریخچه و بازگشت",
            "شروع پیش‌نمایش",
            "تأیید و ثبت در بانک محلی",
            "یکسان‌سازی نام هنرمندان",
        ):
            self.assertIn(text, source)
        for value in ("#282A36", "#44475A", "#BD93F9", "#FF79C6", "#50FA7B"):
            self.assertIn(value, source)
        self.assertIn('"Vazirmatn"', source)
        self.assertIn('anchor="e"', source)
        self.assertIn('justify="right"', source)
        self.assertIn('side="right"', source)

    def test_gui_never_exposes_organizer_apply_or_direct_sqlite(self) -> None:
        for path in UI_FILES:
            source = (PROJECT_ROOT / path).read_text(encoding="utf-8").casefold()
            self.assertNotIn("organizer-apply", source, path)
            self.assertNotIn("bulk-index-apply", source, path)
            self.assertNotIn("import sqlite3", source, path)
            self.assertNotIn("sqlite3.connect", source, path)

    def test_windows_launchers_open_the_user_app(self) -> None:
        root_launcher = (PROJECT_ROOT / "Avachin.bat").read_text(encoding="utf-8").casefold()
        windows_launcher = (PROJECT_ROOT / "scripts" / "windows" / "avachin.bat").read_text(
            encoding="utf-8"
        ).casefold()
        self.assertIn("scripts\\windows\\avachin.bat", root_launcher)
        self.assertIn("tools\\avachin_user_app.py", windows_launcher)
        self.assertNotIn("--apply", root_launcher)
        self.assertNotIn("--apply", windows_launcher)
        self.assertIn("set pythonutf8=1", windows_launcher)

    def test_font_is_selected_from_installed_system_fonts(self) -> None:
        common = (PROJECT_ROOT / "tools" / "persian_ui_common.py").read_text(encoding="utf-8")
        expected_order = ("Vazirmatn", "Vazir", "Vazir UI", "Tahoma", "Segoe UI")
        positions = [common.index(f'"{name}"') for name in expected_order]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
