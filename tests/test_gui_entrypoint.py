#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GuiEntrypointTests(unittest.TestCase):
    def test_windows_launcher_targets_preview_gui(self) -> None:
        launcher = (
            PROJECT_ROOT / "scripts" / "windows" / "gui_preview.bat"
        ).read_text(encoding="utf-8")
        self.assertIn("tools\\avachin_gui.py", launcher)
        self.assertIn("from tools.version import AVACHIN_VERSION", launcher)
        self.assertNotIn("--apply", launcher.casefold())

    def test_gui_and_controller_do_not_expose_apply_operation(self) -> None:
        gui_source = (PROJECT_ROOT / "tools" / "avachin_gui.py").read_text(
            encoding="utf-8"
        )
        controller_source = (
            PROJECT_ROOT / "tools" / "gui_controller.py"
        ).read_text(encoding="utf-8")
        executable_text = "\n".join(
            line
            for line in (gui_source + "\n" + controller_source).splitlines()
            if not line.lstrip().startswith("#")
        ).casefold()
        self.assertIn('operation="organizer-preview"', executable_text)
        self.assertNotIn("organizer-apply", executable_text)
        self.assertNotIn("bulk-index-apply", executable_text)

    def test_gui_consumes_public_status_and_operation_adapters(self) -> None:
        controller_source = (
            PROJECT_ROOT / "tools" / "gui_controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from tools.avachin_operation import", controller_source)
        self.assertIn("from tools.avachin_status import collect_status", controller_source)
        self.assertNotIn("sqlite3", controller_source)
        self.assertNotIn("smart_music_organizer", controller_source)


if __name__ == "__main__":
    unittest.main()
