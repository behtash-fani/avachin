#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a metadata-free mid-song MP3 clip for partial-match acceptance tests."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError

DEFAULT_FILENAME = "Untitled - Unknown Artist.mp3"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_ffmpeg(project_root: Path) -> Path:
    candidates = [
        project_root / "tools" / "ffmpeg.exe",
        project_root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise RuntimeError(
        "ffmpeg was not found. Install it with: winget install Gyan.FFmpeg "
        "or put ffmpeg.exe in tools\\ffmpeg.exe"
    )


def strip_id3(path: Path) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return
    tags.delete(path)


def create_clip(
    source: Path,
    output_dir: Path,
    *,
    start_seconds: float = 60.0,
    duration_seconds: float = 20.0,
    force: bool = False,
    ffmpeg_path: Path | None = None,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source.suffix.lower() != ".mp3":
        raise ValueError("source must be an MP3 file")
    if start_seconds < 0 or duration_seconds < 12:
        raise ValueError("start must be non-negative and duration must be at least 12 seconds")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / DEFAULT_FILENAME
    if destination.exists() and not force:
        raise FileExistsError(f"destination already exists: {destination}")

    project_root = Path(__file__).resolve().parents[1]
    ffmpeg = ffmpeg_path or find_ffmpeg(project_root)
    source_hash = file_sha256(source)
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if force else "-n",
        "-ss",
        f"{float(start_seconds):.3f}",
        "-i",
        str(source),
        "-t",
        f"{float(duration_seconds):.3f}",
        "-vn",
        "-map_metadata",
        "-1",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(destination),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = " ".join((completed.stderr or completed.stdout or "").split())
        raise RuntimeError(f"ffmpeg failed: {detail[:900]}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("ffmpeg did not create a valid clip")

    strip_id3(destination)
    source_unchanged = file_sha256(source) == source_hash
    return {
        "source": str(source),
        "destination": str(destination),
        "start_seconds": float(start_seconds),
        "duration_seconds": float(duration_seconds),
        "source_unchanged": source_unchanged,
        "ffmpeg": str(ffmpeg),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated mid-song MP3 clip")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(r"C:\Avachin_Clip_Test"))
    parser.add_argument("--start", type=float, default=60.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = create_clip(
            args.source,
            args.output_dir,
            start_seconds=args.start,
            duration_seconds=args.duration,
            force=args.force,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("Avachin mid-song acceptance-test clip created")
    print(f"  source: {result['source']}")
    print(f"  destination: {result['destination']}")
    print(f"  clip: {result['start_seconds']:.1f}s to {result['start_seconds'] + result['duration_seconds']:.1f}s")
    print(f"  source unchanged: {'yes' if result['source_unchanged'] else 'NO'}")
    print(f"  ffmpeg: {result['ffmpeg']}")
    print()
    print(f"Use this folder for Preview: {args.output_dir.expanduser().resolve()}")
    return 0 if result["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
