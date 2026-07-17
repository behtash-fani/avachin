#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import io
import os
import shutil
import sys
import urllib.request
import zipfile

VERSION = "1.6.0"
URL = (
    "https://github.com/acoustid/chromaprint/releases/download/"
    f"v{VERSION}/chromaprint-fpcalc-{VERSION}-windows-x86_64.zip"
)

script_dir = Path(__file__).resolve().parent
destination = script_dir / "fpcalc.exe"

if os.name != "nt":
    print("Automatic fpcalc installation is only needed on Windows.")
    print("Install Chromaprint with your system package manager.")
    raise SystemExit(0)

if destination.exists():
    print(f"fpcalc already exists: {destination}")
    raise SystemExit(0)

print(f"Downloading Chromaprint fpcalc {VERSION}...")
request = urllib.request.Request(
    URL,
    headers={"User-Agent": "SmartMusicOrganizer/8.0"},
)

with urllib.request.urlopen(request, timeout=120) as response:
    data = response.read()

with zipfile.ZipFile(io.BytesIO(data)) as archive:
    matches = [
        name for name in archive.namelist()
        if Path(name).name.lower() == "fpcalc.exe"
    ]
    if not matches:
        raise RuntimeError("fpcalc.exe was not found in the downloaded archive.")

    with archive.open(matches[0]) as source, destination.open("wb") as target:
        shutil.copyfileobj(source, target)

print(f"Installed: {destination}")
