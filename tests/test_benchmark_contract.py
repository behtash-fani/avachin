#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark_contract import (  # noqa: E402
    BenchmarkManifest,
    generated_samples,
    stable_sample_id,
)


class BenchmarkContractTests(unittest.TestCase):
    def manifest(self) -> BenchmarkManifest:
        return BenchmarkManifest.from_mapping(
            {
                "schema_version": 1,
                "name": "Hard negatives",
                "seed": 42,
                "references": [
                    {
                        "recording_id": "pedar-studio",
                        "path": "references/pedar-studio.mp3",
                        "title": "Pedar",
                        "artist": "Shahrokh",
                        "duration_seconds": 200,
                        "version": "studio",
                        "hard_negative_group": "pedar-versions",
                        "identifiers": {"avachin": "101"},
                    },
                    {
                        "recording_id": "pedar-live",
                        "path": "references/pedar-live.mp3",
                        "title": "Pedar",
                        "artist": "Shahrokh",
                        "duration_seconds": 230,
                        "version": "live",
                        "hard_negative_group": "pedar-versions",
                        "identifiers": {"avachin": "102"},
                    },
                ],
                "transforms": [
                    {"transform_id": "clean", "kind": "identity"},
                    {
                        "transform_id": "middle-10",
                        "kind": "clip",
                        "parameters": {
                            "duration_seconds": 10,
                            "position": "middle",
                        },
                    },
                ],
            }
        )

    def test_shared_text_key_is_ambiguous_not_correct_for_both(self) -> None:
        manifest = self.manifest()
        self.assertEqual(
            manifest.ambiguous_identity_keys(),
            ("text:shahrokh|pedar",),
        )
        owners = manifest.identity_owner_map()
        self.assertEqual(owners["avachin:101"], "pedar-studio")
        self.assertEqual(owners["avachin:102"], "pedar-live")
        self.assertNotIn("text:shahrokh|pedar", owners)
        samples = generated_samples(manifest)
        studio = next(
            sample
            for sample in samples
            if sample.expected_recording_id == "pedar-studio"
        )
        self.assertEqual(studio.expected_identity_keys, ("avachin:101",))

    def test_sample_ids_and_paths_are_deterministic(self) -> None:
        manifest = self.manifest()
        first = generated_samples(manifest)
        second = generated_samples(manifest)
        self.assertEqual(first, second)
        self.assertEqual(
            first[0].sample_id,
            stable_sample_id("pedar-studio", "clean"),
        )
        self.assertTrue(first[0].path.startswith("generated/pedar-studio/"))

    def test_hard_negative_group_requires_two_references(self) -> None:
        payload = {
            "schema_version": 1,
            "references": [
                {
                    "recording_id": "one",
                    "path": "references/one.mp3",
                    "title": "One",
                    "artist": "Artist",
                    "duration_seconds": 100,
                    "hard_negative_group": "lonely",
                }
            ],
            "transforms": [{"transform_id": "clean", "kind": "identity"}],
        }
        with self.assertRaisesRegex(ValueError, "at least two references"):
            BenchmarkManifest.from_mapping(payload)

    def test_reference_path_cannot_escape_corpus(self) -> None:
        payload = {
            "schema_version": 1,
            "references": [
                {
                    "recording_id": "one",
                    "path": "../outside.mp3",
                    "title": "One",
                    "artist": "Artist",
                    "duration_seconds": 100,
                }
            ],
            "transforms": [{"transform_id": "clean", "kind": "identity"}],
        }
        with self.assertRaisesRegex(ValueError, "safe relative path"):
            BenchmarkManifest.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
