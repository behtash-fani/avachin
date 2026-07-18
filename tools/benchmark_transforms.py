#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic FFmpeg transform generation for Avachin benchmarks."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from tools.benchmark_contract import GeneratedSample, ReferenceRecording, TransformSpec


@dataclass(frozen=True)
class TransformCommand:
    sample_id: str
    source: Path
    output: Path
    command: tuple[str, ...]
    kind: str
    seed: int


def deterministic_seed(global_seed: int, recording_id: str, transform_id: str) -> int:
    digest = hashlib.sha256(
        f"{global_seed}\0{recording_id}\0{transform_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _number(parameters: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(parameters.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"transform parameter {key!r} must be numeric") from exc


def _integer(parameters: dict[str, Any], key: str, default: int) -> int:
    value = _number(parameters, key, float(default))
    if int(value) != value:
        raise ValueError(f"transform parameter {key!r} must be an integer")
    return int(value)


def _audio_output_args(parameters: dict[str, Any]) -> list[str]:
    bitrate = _integer(parameters, "output_bitrate_kbps", 128)
    if bitrate <= 0:
        raise ValueError("output_bitrate_kbps must be greater than zero")
    return ["-vn", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]


def build_transform_command(
    *,
    ffmpeg: str,
    source: Path,
    output: Path,
    recording: ReferenceRecording,
    transform: TransformSpec,
    global_seed: int,
) -> TransformCommand:
    parameters = dict(transform.parameters)
    seed = deterministic_seed(global_seed, recording.recording_id, transform.transform_id)
    base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    suffix = _audio_output_args(parameters)
    kind = transform.kind

    if kind == "identity":
        command: list[str] = []
    elif kind == "clip":
        duration = _number(parameters, "duration_seconds", 10.0)
        if duration <= 0 or duration > recording.duration_seconds:
            raise ValueError("clip duration must be within the reference duration")
        position = str(parameters.get("position") or "middle").casefold()
        if "offset_seconds" in parameters:
            start = _number(parameters, "offset_seconds", 0.0)
        elif position == "start":
            start = 0.0
        elif position == "end":
            start = recording.duration_seconds - duration
        elif position == "middle":
            start = (recording.duration_seconds - duration) / 2.0
        else:
            raise ValueError("clip position must be start, middle or end")
        if start < 0 or start + duration > recording.duration_seconds + 0.001:
            raise ValueError("clip offset is outside the reference duration")
        command = [
            *base,
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            *suffix,
            str(output),
        ]
    elif kind == "bitrate":
        bitrate = _integer(parameters, "bitrate_kbps", 128)
        if bitrate not in {32, 48, 64, 96, 128, 192, 256, 320}:
            raise ValueError("unsupported benchmark bitrate")
        command = [
            *base,
            "-i",
            str(source),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate}k",
            str(output),
        ]
    elif kind == "trim":
        head = _number(parameters, "head_seconds", 0.0)
        tail = _number(parameters, "tail_seconds", 0.0)
        remaining = recording.duration_seconds - head - tail
        if head < 0 or tail < 0 or remaining <= 0:
            raise ValueError("trim removes the complete reference")
        command = [
            *base,
            "-ss",
            f"{head:.3f}",
            "-t",
            f"{remaining:.3f}",
            "-i",
            str(source),
            *suffix,
            str(output),
        ]
    elif kind == "silence":
        seconds = _number(parameters, "leading_seconds", 2.0)
        if seconds < 0:
            raise ValueError("leading_seconds must not be negative")
        delay_ms = int(round(seconds * 1000))
        command = [
            *base,
            "-i",
            str(source),
            "-af",
            f"adelay={delay_ms}:all=1",
            *suffix,
            str(output),
        ]
    elif kind == "volume":
        decibels = _number(parameters, "decibels", -6.0)
        if decibels < -60 or decibels > 20:
            raise ValueError("volume decibels must be between -60 and 20")
        command = [
            *base,
            "-i",
            str(source),
            "-af",
            f"volume={decibels:g}dB",
            *suffix,
            str(output),
        ]
    elif kind == "noise":
        amplitude = _number(parameters, "amplitude", 0.015)
        if amplitude <= 0 or amplitude > 1:
            raise ValueError("noise amplitude must be within (0, 1]")
        color = str(parameters.get("color") or "white").casefold()
        if color not in {"white", "pink", "brown", "blue", "violet"}:
            raise ValueError("unsupported noise color")
        duration = recording.duration_seconds
        graph = (
            f"anoisesrc=color={color}:amplitude={amplitude:g}:"
            f"duration={duration:.3f}:seed={seed}[noise];"
            "[0:a][noise]amix=inputs=2:duration=first:"
            "dropout_transition=0[out]"
        )
        command = [
            *base,
            "-i",
            str(source),
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            *suffix,
            str(output),
        ]
    else:
        raise ValueError(f"unsupported transform kind: {kind}")

    return TransformCommand(
        sample_id="",
        source=source,
        output=output,
        command=tuple(command),
        kind=kind,
        seed=seed,
    )


def materialize_sample(
    *,
    sample: GeneratedSample,
    recording: ReferenceRecording,
    transform: TransformSpec,
    corpus_root: Path,
    ffmpeg: str,
    global_seed: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> TransformCommand:
    corpus_root = Path(corpus_root).resolve()
    source = (corpus_root / sample.source_reference_path).resolve()
    output = (corpus_root / sample.path).resolve()
    source.relative_to(corpus_root)
    output.relative_to(corpus_root)
    if not source.is_file():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = build_transform_command(
        ffmpeg=ffmpeg,
        source=source,
        output=output,
        recording=recording,
        transform=transform,
        global_seed=global_seed,
    )
    command = TransformCommand(
        sample_id=sample.sample_id,
        source=command.source,
        output=command.output,
        command=command.command,
        kind=command.kind,
        seed=command.seed,
    )
    if transform.kind == "identity":
        shutil.copy2(source, output)
    else:
        completed = runner(
            list(command.command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "FFmpeg failed").strip()
            raise RuntimeError(f"transform {sample.sample_id} failed: {message[:1000]}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"transform produced no output: {output}")
    return command


def materialize_all(
    *,
    samples: Iterable[GeneratedSample],
    references: Sequence[ReferenceRecording],
    transforms: Sequence[TransformSpec],
    corpus_root: Path,
    ffmpeg: str,
    global_seed: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[TransformCommand]:
    reference_map = {item.recording_id: item for item in references}
    transform_map = {item.transform_id: item for item in transforms}
    commands: list[TransformCommand] = []
    for sample in samples:
        commands.append(
            materialize_sample(
                sample=sample,
                recording=reference_map[sample.expected_recording_id],
                transform=transform_map[sample.transform_id],
                corpus_root=corpus_root,
                ffmpeg=ffmpeg,
                global_seed=global_seed,
                runner=runner,
            )
        )
    return commands
