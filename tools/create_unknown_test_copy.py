#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create an isolated, metadata-free MP3 copy for local-first acceptance tests.

The source file is never modified. The destination receives the same audio
frames with ID3 metadata removed and a deliberately unknown filename so the
organizer must rely on acoustic identity instead of tags or path hints.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
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


def strip_id3(path: Path) -> bool:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        return False
    tags.delete(path)
    return True


def create_test_copy(source: Path, output_dir: Path, *, force: bool = False) -> dict[str, object]:
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(str(source))
    if source.suffix.lower() != ".mp3":
        raise ValueError("source must be an MP3 file")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / DEFAULT_FILENAME

    if destination.resolve() == source:
        raise ValueError("destination must be different from source")
    if destination.exists() and not force:
        raise FileExistsError(f"destination already exists: {destination}")

    source_sha = file_sha256(source)
    shutil.copy2(source, destination)
    tags_removed = strip_id3(destination)
    destination_sha = file_sha256(destination)

    return {
        "source": str(source),
        "destination": str(destination),
        "source_sha256": source_sha,
        "destination_sha256": destination_sha,
        "tags_removed": tags_removed,
        "source_unchanged": file_sha256(source) == source_sha,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated unknown MP3 test copy")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(r"C:\Avachin_Test"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        result = create_test_copy(args.source, args.output_dir, force=args.force)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("Avachin isolated acceptance-test copy created")
    print(f"  source: {result['source']}")
    print(f"  destination: {result['destination']}")
    print(f"  ID3 tags removed: {'yes' if result['tags_removed'] else 'no tags were present'}")
    print(f"  source unchanged: {'yes' if result['source_unchanged'] else 'NO'}")
    print()
    print(f"Use this folder for Preview: {args.output_dir.expanduser().resolve()}")
    return 0 if result["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
