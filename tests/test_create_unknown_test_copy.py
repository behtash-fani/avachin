#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from mutagen.id3 import ID3, TIT2, TPE1, ID3NoHeaderError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import create_unknown_test_copy as fixture  # noqa: E402


class UnknownTestCopyTests(unittest.TestCase):
    def make_tagged_file(self, root: Path) -> Path:
        source = root / "Baazi - Siavash Ghomayshi.mp3"
        source.write_bytes(b"\xff\xfb\x90\x64" + (b"audio-frame" * 100))
        tags = ID3()
        tags.add(TIT2(encoding=3, text="Baazi"))
        tags.add(TPE1(encoding=3, text="Siavash Ghomayshi"))
        tags.save(source)
        return source

    def test_creates_unknown_copy_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = self.make_tagged_file(root)
            before = fixture.file_sha256(source)

            result = fixture.create_test_copy(source, root / "test-output")
            destination = Path(str(result["destination"]))

            self.assertTrue(destination.is_file())
            self.assertEqual(destination.name, fixture.DEFAULT_FILENAME)
            self.assertEqual(fixture.file_sha256(source), before)
            self.assertTrue(result["source_unchanged"])
            self.assertTrue(result["tags_removed"])
            with self.assertRaises(ID3NoHeaderError):
                ID3(destination)

    def test_refuses_existing_destination_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = self.make_tagged_file(root)
            output = root / "test-output"
            fixture.create_test_copy(source, output)
            with self.assertRaises(FileExistsError):
                fixture.create_test_copy(source, output)


if __name__ == "__main__":
    unittest.main()
