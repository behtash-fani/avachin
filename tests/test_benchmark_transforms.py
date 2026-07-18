#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_contract import (  # noqa: E402
    GeneratedSample,
    ReferenceRecording,
    TransformSpec,
)
from tools.benchmark_transforms import (  # noqa: E402
    build_transform_command,
    deterministic_seed,
    materialize_sample,
)


class BenchmarkTransformTests(unittest.TestCase):
    def reference(self) -> ReferenceRecording:
        return ReferenceRecording(
            recording_id="recording-1",
            path="references/source.mp3",
            title="Song",
            artist="Artist",
            duration_seconds=200.0,
            identity_keys=("avachin:1",),
        )

    def test_seed_is_stable_and_transform_specific(self) -> None:
        first = deterministic_seed(42, "recording-1", "noise")
        second = deterministic_seed(42, "recording-1", "noise")
        other = deterministic_seed(42, "recording-1", "noise-2")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_middle_clip_uses_expected_offset(self) -> None:
        command = build_transform_command(
            ffmpeg="ffmpeg",
            source=Path("source.mp3"),
            output=Path("output.mp3"),
            recording=self.reference(),
            transform=TransformSpec(
                "middle-10",
                "clip",
                {"duration_seconds": 10, "position": "middle"},
            ),
            global_seed=42,
        )
        joined = " ".join(command.command)
        self.assertIn("-ss 95.000", joined)
        self.assertIn("-t 10.000", joined)

    def test_noise_command_contains_deterministic_seed(self) -> None:
        transform = TransformSpec(
            "noise-white",
            "noise",
            {"amplitude": 0.02, "color": "white"},
        )
        command = build_transform_command(
            ffmpeg="ffmpeg",
            source=Path("source.mp3"),
            output=Path("output.mp3"),
            recording=self.reference(),
            transform=transform,
            global_seed=42,
        )
        joined = " ".join(command.command)
        self.assertIn(f"seed={command.seed}", joined)
        self.assertIn("amix=inputs=2:duration=first", joined)

    def test_identity_transform_copies_fixture_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "references" / "source.mp3"
            source.parent.mkdir()
            source.write_bytes(b"audio fixture")
            sample = GeneratedSample(
                sample_id="sample-1",
                expected_recording_id="recording-1",
                source_reference_path="references/source.mp3",
                path="generated/recording-1/clean.mp3",
                transform_id="clean",
                transform_kind="identity",
                split="validation",
                version="studio",
                hard_negative_group="",
                expected_identity_keys=("avachin:1",),
            )
            command = materialize_sample(
                sample=sample,
                recording=self.reference(),
                transform=TransformSpec("clean", "identity"),
                corpus_root=root,
                ffmpeg="missing-ffmpeg-is-unused",
                global_seed=42,
            )
            self.assertEqual(command.command, ())
            self.assertEqual(
                (root / sample.path).read_bytes(),
                b"audio fixture",
            )

    def test_invalid_trim_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "complete reference"):
            build_transform_command(
                ffmpeg="ffmpeg",
                source=Path("source.mp3"),
                output=Path("output.mp3"),
                recording=self.reference(),
                transform=TransformSpec(
                    "bad-trim",
                    "trim",
                    {"head_seconds": 150, "tail_seconds": 60},
                ),
                global_seed=42,
            )


if __name__ == "__main__":
    unittest.main()
