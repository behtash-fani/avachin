#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned contracts for Avachin benchmark corpora and evaluation rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

BENCHMARK_SCHEMA_VERSION = 1
ALLOWED_SPLITS = {"reference", "validation", "test"}
ALLOWED_TRANSFORMS = {
    "identity",
    "clip",
    "bitrate",
    "trim",
    "silence",
    "noise",
    "volume",
}
AUTO_APPLY_DECISIONS = {"LOCAL_MATCH", "AUTO_LEARN"}


def stable_sample_id(recording_id: str, transform_id: str) -> str:
    digest = hashlib.sha256(
        f"{recording_id}\0{transform_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"sample-{digest}"


def normalize_identity_key(value: object) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if ":" not in text:
        return text.casefold()
    prefix, payload = text.split(":", 1)
    return f"{prefix.casefold()}:{payload.strip().casefold()}"


def text_identity_key(artist: object, title: object) -> str:
    artist_key = " ".join(str(artist or "").casefold().split())
    title_key = " ".join(str(title or "").casefold().split())
    return f"text:{artist_key}|{title_key}" if artist_key and title_key else ""


def _relative_path(value: object, *, field_name: str) -> str:
    pure = PurePosixPath(str(value or ""))
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"{field_name} must be a safe relative path")
    return pure.as_posix()


def _string_tuple(values: object, *, field_name: str) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    if not isinstance(values, (list, tuple, set)):
        raise ValueError(f"{field_name} must be a list of strings")
    result = tuple(
        value
        for value in (
            normalize_identity_key(item) for item in values
        )
        if value
    )
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} contains duplicate values")
    return result


@dataclass(frozen=True)
class ReferenceRecording:
    recording_id: str
    path: str
    title: str
    artist: str
    duration_seconds: float
    split: str = "validation"
    version: str = "studio"
    hard_negative_group: str = ""
    identity_keys: tuple[str, ...] = ()
    identifiers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ReferenceRecording":
        recording_id = str(raw.get("recording_id") or "").strip()
        title = " ".join(str(raw.get("title") or "").split())
        artist = " ".join(str(raw.get("artist") or "").split())
        if not recording_id or not title or not artist:
            raise ValueError("each reference requires recording_id, title and artist")
        split = str(raw.get("split") or "validation").casefold()
        if split not in ALLOWED_SPLITS:
            raise ValueError(f"unsupported benchmark split: {split}")
        try:
            duration = float(raw.get("duration_seconds") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_seconds must be numeric") from exc
        if duration <= 0:
            raise ValueError("duration_seconds must be greater than zero")
        identifiers = {
            str(key).casefold(): str(value).strip()
            for key, value in dict(raw.get("identifiers") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        keys = list(_string_tuple(raw.get("identity_keys"), field_name="identity_keys"))
        keys.extend(
            normalize_identity_key(f"{key}:{value}")
            for key, value in identifiers.items()
        )
        text_key = text_identity_key(artist, title)
        if text_key:
            keys.append(text_key)
        keys = list(dict.fromkeys(key for key in keys if key))
        return cls(
            recording_id=recording_id,
            path=_relative_path(raw.get("path"), field_name="reference path"),
            title=title,
            artist=artist,
            duration_seconds=duration,
            split=split,
            version=str(raw.get("version") or "studio").strip().casefold(),
            hard_negative_group=str(raw.get("hard_negative_group") or "").strip(),
            identity_keys=tuple(keys),
            identifiers=identifiers,
        )


@dataclass(frozen=True)
class TransformSpec:
    transform_id: str
    kind: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TransformSpec":
        transform_id = str(raw.get("transform_id") or raw.get("id") or "").strip()
        kind = str(raw.get("kind") or "").strip().casefold()
        if not transform_id:
            raise ValueError("each transform requires transform_id")
        if kind not in ALLOWED_TRANSFORMS:
            raise ValueError(f"unsupported transform kind: {kind!r}")
        parameters = dict(raw.get("parameters") or {})
        return cls(transform_id=transform_id, kind=kind, parameters=parameters)


@dataclass(frozen=True)
class GeneratedSample:
    sample_id: str
    expected_recording_id: str
    source_reference_path: str
    path: str
    transform_id: str
    transform_kind: str
    split: str
    version: str
    hard_negative_group: str
    expected_identity_keys: tuple[str, ...]
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_identity_keys"] = list(self.expected_identity_keys)
        return payload


@dataclass(frozen=True)
class BenchmarkManifest:
    name: str
    seed: int
    references: tuple[ReferenceRecording, ...]
    transforms: tuple[TransformSpec, ...]
    schema_version: int = BENCHMARK_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "BenchmarkManifest":
        if int(raw.get("schema_version") or 0) != BENCHMARK_SCHEMA_VERSION:
            raise ValueError("unsupported benchmark manifest schema")
        references = tuple(
            ReferenceRecording.from_mapping(item)
            for item in raw.get("references") or []
        )
        transforms = tuple(
            TransformSpec.from_mapping(item)
            for item in raw.get("transforms") or []
        )
        if not references:
            raise ValueError("benchmark manifest requires at least one reference")
        if not transforms:
            raise ValueError("benchmark manifest requires at least one transform")
        reference_ids = [item.recording_id for item in references]
        transform_ids = [item.transform_id for item in transforms]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("duplicate recording_id in benchmark references")
        if len(transform_ids) != len(set(transform_ids)):
            raise ValueError("duplicate transform_id in benchmark manifest")
        groups: dict[str, list[ReferenceRecording]] = {}
        for reference in references:
            if reference.hard_negative_group:
                groups.setdefault(reference.hard_negative_group, []).append(reference)
        invalid_groups = [name for name, items in groups.items() if len(items) < 2]
        if invalid_groups:
            raise ValueError(
                "hard_negative_group requires at least two references: "
                + ", ".join(sorted(invalid_groups))
            )
        return cls(
            name=str(raw.get("name") or "Avachin benchmark").strip(),
            seed=int(raw.get("seed") or 0),
            references=references,
            transforms=transforms,
        )

    @classmethod
    def load(cls, path: Path) -> "BenchmarkManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("benchmark manifest must be a JSON object")
        return cls.from_mapping(payload)

    def reference_map(self) -> dict[str, ReferenceRecording]:
        return {item.recording_id: item for item in self.references}

    def identity_owner_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for reference in self.references:
            for key in reference.identity_keys:
                owner = result.get(key)
                if owner and owner != reference.recording_id:
                    raise ValueError(f"identity key is shared by multiple references: {key}")
                result[key] = reference.recording_id
        return result


def generated_samples(
    manifest: BenchmarkManifest,
    *,
    generated_root: str = "generated",
) -> tuple[GeneratedSample, ...]:
    samples: list[GeneratedSample] = []
    for reference in manifest.references:
        suffix = Path(reference.path).suffix.casefold() or ".mp3"
        for transform in manifest.transforms:
            sample_id = stable_sample_id(reference.recording_id, transform.transform_id)
            relative = PurePosixPath(
                generated_root,
                reference.recording_id,
                f"{sample_id}-{transform.transform_id}{suffix}",
            ).as_posix()
            samples.append(
                GeneratedSample(
                    sample_id=sample_id,
                    expected_recording_id=reference.recording_id,
                    source_reference_path=reference.path,
                    path=relative,
                    transform_id=transform.transform_id,
                    transform_kind=transform.kind,
                    split=reference.split,
                    version=reference.version,
                    hard_negative_group=reference.hard_negative_group,
                    expected_identity_keys=reference.identity_keys,
                    parameters=dict(transform.parameters),
                )
            )
    return tuple(samples)


def write_generated_manifest(
    path: Path,
    manifest: BenchmarkManifest,
    samples: Iterable[GeneratedSample],
) -> Path:
    payload = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "name": manifest.name,
        "seed": manifest.seed,
        "references": [asdict(item) for item in manifest.references],
        "samples": [item.to_dict() for item in samples],
    }
    for reference in payload["references"]:
        reference["identity_keys"] = list(reference["identity_keys"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
