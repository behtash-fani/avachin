#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import audio_repair  # noqa: E402


class AudioRepairTests(unittest.TestCase):
    def test_temporary_repair_is_validated_and_original_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "damaged.mp3"
            source.write_bytes(b"original-damaged-bytes")
            original_bytes = source.read_bytes()
            repaired_path: Path | None = None

            def fake_run(command: list[str], timeout_seconds: int):
                self.assertGreater(timeout_seconds, 0)
                if "-c:a" in command:
                    output = Path(command[-1])
                    output.write_bytes(b"valid-reencoded-audio")
                    return subprocess.CompletedProcess(command, 0, "", "header warning")
                return subprocess.CompletedProcess(command, 0, "", "")

            config = {
                "audio_repair_enabled": True,
                "audio_repair_temp_dir": str(root / "temp"),
                "audio_repair_keep_temporary_files": False,
            }
            with mock.patch.object(audio_repair, "find_ffmpeg", return_value=root / "ffmpeg"), mock.patch.object(
                audio_repair, "_run_command", side_effect=fake_run
            ):
                with audio_repair.repair_audio_for_analysis(source, config=config) as result:
                    repaired_path = Path(result.repaired_path)
                    self.assertTrue(repaired_path.exists())
                    self.assertNotEqual(repaired_path.resolve(), source.resolve())
                    self.assertEqual(result.method, "ffmpeg-reencode")
                    self.assertTrue(result.temporary)
                    self.assertEqual(result.original_size_bytes, len(original_bytes))
                    self.assertGreater(result.repaired_size_bytes, 0)

            self.assertEqual(source.read_bytes(), original_bytes)
            assert repaired_path is not None
            self.assertFalse(repaired_path.exists())

    def test_failed_repair_does_not_modify_or_delete_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "damaged.mp3"
            source.write_bytes(b"keep-me")

            failed = subprocess.CompletedProcess(
                ["ffmpeg"],
                1,
                "",
                "Invalid data found when processing input",
            )
            with mock.patch.object(audio_repair, "find_ffmpeg", return_value=root / "ffmpeg"), mock.patch.object(
                audio_repair, "_run_command", return_value=failed
            ):
                with self.assertRaises(audio_repair.AudioRepairFailed):
                    with audio_repair.repair_audio_for_analysis(
                        source,
                        config={"audio_repair_temp_dir": str(root / "temp")},
                    ):
                        self.fail("failed repair must not yield a result")

            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"keep-me")

    def test_runtime_retries_decode_failure_with_temporary_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "damaged.mp3"
            repaired = root / "repaired.mp3"
            source.write_bytes(b"damaged")
            repaired.write_bytes(b"repaired")
            calls: list[Path] = []

            def original(path: Path, fpcalc_path=None, timeout: int = 120):
                calls.append(Path(path))
                if Path(path) == source:
                    raise RuntimeError(
                        "fpcalc failed: ERROR: Error reading from the audio source "
                        "(Invalid data found when processing input)"
                    )
                return 115.1, [1, 2, 3, 4]

            @contextmanager
            def fake_repair(path: Path, *, config=None):
                self.assertEqual(Path(path), source)
                yield audio_repair.RepairResult(
                    source_path=str(source),
                    repaired_path=str(repaired),
                    method="ffmpeg-reencode",
                    original_size_bytes=7,
                    repaired_size_bytes=8,
                    temporary=True,
                    retained_for_debugging=False,
                    elapsed_seconds=0.01,
                )

            module = SimpleNamespace(raw_fingerprint=original)
            with mock.patch.object(audio_repair, "repair_audio_for_analysis", side_effect=fake_repair):
                audio_repair.install_fingerprint_repair_runtime(
                    module,
                    config_provider=lambda: {
                        "audio_repair_enabled": True,
                        "audio_repair_only_on_decode_error": True,
                        "audio_repair_log_console": False,
                    },
                )
                result = module.raw_fingerprint(source)

            self.assertEqual(result, (115.1, [1, 2, 3, 4]))
            self.assertEqual(calls, [source, repaired])
            self.assertTrue(
                getattr(module.raw_fingerprint, "__avachin_audio_repair_runtime__", False)
            )

    def test_non_decode_failure_is_not_repaired(self) -> None:
        source = Path("missing-tool.mp3")

        def original(path: Path, fpcalc_path=None, timeout: int = 120):
            raise RuntimeError("fpcalc was not found")

        module = SimpleNamespace(raw_fingerprint=original)
        with mock.patch.object(audio_repair, "repair_audio_for_analysis") as repair:
            audio_repair.install_fingerprint_repair_runtime(
                module,
                config_provider=lambda: {
                    "audio_repair_enabled": True,
                    "audio_repair_only_on_decode_error": True,
                },
            )
            with self.assertRaisesRegex(RuntimeError, "fpcalc was not found"):
                module.raw_fingerprint(source)
            repair.assert_not_called()

    def test_repair_failure_is_reported_without_hiding_original_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "damaged.mp3"
            source.write_bytes(b"damaged")

            def original(path: Path, fpcalc_path=None, timeout: int = 120):
                raise RuntimeError("fpcalc failed: Header missing")

            @contextmanager
            def broken_repair(path: Path, *, config=None):
                raise audio_repair.AudioRepairFailed("validation failed")
                yield  # pragma: no cover

            module = SimpleNamespace(raw_fingerprint=original)
            with mock.patch.object(audio_repair, "repair_audio_for_analysis", side_effect=broken_repair):
                audio_repair.install_fingerprint_repair_runtime(
                    module,
                    config_provider=lambda: {
                        "audio_repair_enabled": True,
                        "audio_repair_only_on_decode_error": True,
                        "audio_repair_log_console": False,
                    },
                )
                with self.assertRaisesRegex(
                    RuntimeError,
                    "fpcalc failed: Header missing; automatic temporary audio repair failed: validation failed",
                ):
                    module.raw_fingerprint(source)

            self.assertEqual(source.read_bytes(), b"damaged")

    def test_listener_errors_cannot_break_repair_notifications(self) -> None:
        received: list[str] = []

        def broken_listener(event: audio_repair.RepairEvent) -> None:
            raise RuntimeError("UI listener failed")

        def working_listener(event: audio_repair.RepairEvent) -> None:
            received.append(event.status)

        audio_repair.register_repair_listener(broken_listener)
        audio_repair.register_repair_listener(working_listener)
        try:
            audio_repair._emit(
                audio_repair.RepairEvent(status="succeeded", source_path="track.mp3")
            )
        finally:
            audio_repair.unregister_repair_listener(broken_listener)
            audio_repair.unregister_repair_listener(working_listener)

        self.assertEqual(received, ["succeeded"])

    def test_direct_cli_help_from_project_root(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/audio_repair.py", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("without modifying the original audio", completed.stdout)


if __name__ == "__main__":
    unittest.main()
