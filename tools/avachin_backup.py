#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-command backup and safe restore for Avachin project and local state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import smart_music_organizer as app  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402

BACKUP_SCHEMA_VERSION = 1
MANIFEST_NAME = "backup-manifest.json"
BACKUP_DIRNAME = "backups"
DEFAULT_BACKUP_DIRNAME = BACKUP_DIRNAME
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SQLITE_SIDECARS = ("-wal", "-shm", "-journal")
PROJECT_ROOTS = (".github", "docs", "reference_data", "scripts", "tests", "tools")
PROJECT_FILES = (
    ".gitignore", "README.md", "configure.py", "config.json",
    "config.example.json", "config.local.example.json", "requirements.txt",
    "smart_music_organizer.py",
)
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", "cache", "logs", "output", "organized", "Review", "Conflicts",
}
GROUPS = {"project", "app_data", "reports", "external"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp_token() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(str(value or ""))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"unsafe archive-relative path: {value!r}")
    return Path(*pure.parts)


def _json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return dict(value) if isinstance(value, dict) else {}


def load_config(project_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("config.json", "config.local.json"):
        try:
            result.update(_json_object(project_root / name))
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _git(project_root: Path, *args: str, binary: bool = False) -> Any:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *args], capture_output=True,
            text=not binary, encoding=None if binary else "utf-8",
            errors=None if binary else "replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return b"" if binary else ""
    return completed.stdout if completed.returncode == 0 else (b"" if binary else "")


def git_commit(project_root: Path) -> str:
    return str(_git(project_root, "rev-parse", "HEAD")).strip()


def _fallback_project_files(project_root: Path) -> list[Path]:
    result = [(project_root / name).resolve() for name in PROJECT_FILES if (project_root / name).is_file()]
    for root_name in PROJECT_ROOTS:
        root = project_root / root_name
        if not root.is_dir():
            continue
        result.extend(
            path.resolve() for path in root.rglob("*")
            if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
        )
    return result


def _git_tracked_files(project_root: Path) -> list[Path]:
    raw = _git(project_root, "ls-files", "-z", binary=True)
    result: list[Path] = []
    for item in raw.split(b"\x00") if raw else []:
        if not item:
            continue
        path = (project_root / Path(os.fsdecode(item))).resolve()
        if path.is_file() and _inside(path, project_root):
            result.append(path)
    return result


def project_files(project_root: Path) -> list[Path]:
    result = _git_tracked_files(project_root) or _fallback_project_files(project_root)
    local_config = (project_root / "config.local.json").resolve()
    if local_config.is_file():
        result.append(local_config)
    return sorted(set(result), key=lambda value: str(value).casefold())


def recursive_files(root: Path, excluded: Iterable[Path] = ()) -> list[Path]:
    if not root.is_dir():
        return []
    blocked = {path.resolve() for path in excluded}
    result: list[Path] = []
    for path in root.rglob("*"):
        resolved = path.resolve()
        if any(_inside(resolved, base) for base in blocked):
            continue
        if path.is_file() and not path.is_symlink():
            result.append(resolved)
    return sorted(set(result), key=lambda value: str(value).casefold())


@dataclass(frozen=True)
class Source:
    group: str
    path: Path
    relative: Path
    original_path: str = ""

    @property
    def member(self) -> str:
        return PurePosixPath("payload", self.group, *self.relative.parts).as_posix()


@dataclass(frozen=True)
class ManifestFile:
    group: str
    relative_path: str
    archive_path: str
    size: int
    sha256: str
    original_path: str = ""


def discover_sources(
    project_root: Path, app_data_dir: Path, *, include_reports: bool = True,
    output_dir: Path | None = None,
) -> list[Source]:
    project_root, app_data_dir = project_root.resolve(), app_data_dir.resolve()
    result: list[Source] = []
    seen: set[Path] = set()

    def add(group: str, path: Path, relative: Path, original: str = "") -> None:
        resolved = path.resolve()
        if resolved.is_file() and resolved not in seen:
            seen.add(resolved)
            result.append(Source(group, resolved, relative, original))

    for path in project_files(project_root):
        add("project", path, path.relative_to(project_root))

    excluded = [app_data_dir / BACKUP_DIRNAME]
    if output_dir is not None and _inside(output_dir.resolve(), app_data_dir):
        excluded.append(output_dir.resolve())
    for path in recursive_files(app_data_dir, excluded):
        if not path.name.casefold().endswith(SQLITE_SIDECARS):
            add("app_data", path, path.relative_to(app_data_dir))

    reports = project_root / "reports"
    if include_reports:
        for path in recursive_files(reports):
            add("reports", path, path.relative_to(reports))

    configured = str(load_config(project_root).get("audd_request_budget_db_path") or "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file() and not _inside(path, project_root) and not _inside(path, app_data_dir):
            add("external", path, Path("audd-provider-usage.sqlite3"), str(path))
    return sorted(result, key=lambda item: item.member.casefold())


def _sqlite(path: Path) -> bool:
    if path.suffix.casefold() not in SQLITE_SUFFIXES:
        return False
    try:
        with path.open("rb") as stream:
            return stream.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _snapshot(source: Source, staging: Path) -> Path:
    if not _sqlite(source.path):
        return source.path
    destination = staging / hashlib.sha256(source.member.encode()).hexdigest()
    connection = sqlite3.connect(source.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        output = sqlite3.connect(destination)
        try:
            connection.backup(output)
        finally:
            output.close()
    finally:
        connection.close()
    return destination


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def create_backup(
    *, project_root: Path = PROJECT_ROOT, app_data_dir: Path | None = None,
    output_path: Path | None = None, include_reports: bool = True,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    app_data_dir = Path(app_data_dir or app.app_data_dir()).resolve()
    default = app_data_dir / BACKUP_DIRNAME / f"avachin-backup-{timestamp_token()}.zip"
    output_path = Path(output_path or default).expanduser().resolve()
    if output_path.suffix.casefold() != ".zip":
        raise ValueError("backup output path must use the .zip extension")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sources = discover_sources(
        project_root, app_data_dir, include_reports=include_reports,
        output_dir=output_path.parent,
    )
    if not sources:
        raise RuntimeError("no Avachin project or local-state files were found to back up")

    started = time.monotonic()
    files: list[ManifestFile] = []
    with tempfile.TemporaryDirectory(prefix="avachin-backup-") as temp_dir:
        staging = Path(temp_dir)
        temporary_zip = staging / "backup.zip"
        with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for source in sources:
                materialized = _snapshot(source, staging)
                item = ManifestFile(
                    source.group, PurePosixPath(*source.relative.parts).as_posix(),
                    source.member, materialized.stat().st_size,
                    sha256_file(materialized), source.original_path,
                )
                archive.write(materialized, item.archive_path)
                files.append(item)
            manifest = {
                "schema_version": BACKUP_SCHEMA_VERSION, "created_at": utc_now(),
                "avachin_version": AVACHIN_VERSION, "git_commit": git_commit(project_root),
                "project_root": str(project_root), "app_data_dir": str(app_data_dir),
                "include_reports": include_reports, "files": [asdict(item) for item in files],
            }
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        temporary_output = output_path.with_name(output_path.name + f".{os.getpid()}.tmp")
        shutil.copyfile(temporary_zip, temporary_output)
        temporary_output.replace(output_path)
    try:
        output_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    result = {
        "status": "completed", "archive": str(output_path),
        "created_at": utc_now(), "avachin_version": AVACHIN_VERSION,
        "git_commit": manifest["git_commit"], "files": len(files),
        "bytes": sum(item.size for item in files),
        "groups": {group: sum(item.group == group for item in files) for group in sorted(GROUPS)},
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    report = output_path.with_suffix(".json")
    _atomic_json(report, result)
    result["report"] = str(report)
    return result


def read_manifest(archive_path: Path) -> tuple[dict[str, Any], list[ManifestFile]]:
    with zipfile.ZipFile(Path(archive_path).resolve(), "r") as archive:
        try:
            payload = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError as exc:
            raise ValueError(f"backup archive is missing {MANIFEST_NAME}") from exc
    if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != BACKUP_SCHEMA_VERSION:
        raise ValueError("unsupported or invalid Avachin backup manifest")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("backup manifest contains no files")
    files: list[ManifestFile] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ValueError("backup manifest file entries must be objects")
        item = ManifestFile(
            str(raw.get("group") or ""), str(raw.get("relative_path") or ""),
            str(raw.get("archive_path") or ""), int(raw.get("size") or 0),
            str(raw.get("sha256") or ""), str(raw.get("original_path") or ""),
        )
        if item.group not in GROUPS:
            raise ValueError(f"unsupported backup group: {item.group!r}")
        relative = _safe_relative(item.relative_path)
        member = PurePosixPath(*_safe_relative(item.archive_path).parts).as_posix()
        expected = PurePosixPath("payload", item.group, *relative.parts).as_posix()
        if member != expected:
            raise ValueError(f"archive path does not match group {item.group!r}: {item.archive_path!r}")
        if member in seen:
            raise ValueError(f"duplicate backup archive path: {member}")
        seen.add(member)
        if len(item.sha256) != 64 or item.size < 0:
            raise ValueError(f"invalid hash/size for {member}")
        files.append(item)
    return payload, files


def _member_hash(archive: zipfile.ZipFile, name: str) -> tuple[int, str]:
    size, digest = 0, hashlib.sha256()
    with archive.open(name) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_archive(archive_path: Path, files: Sequence[ManifestFile]) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = [item.filename for item in archive.infolist()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"backup contains duplicate ZIP members: {', '.join(duplicates)}")
        available = set(names)
        expected = {MANIFEST_NAME, *(item.archive_path for item in files)}
        undeclared = sorted(name for name in available - expected if name.startswith("payload/"))
        if undeclared:
            raise ValueError("backup contains undeclared payload members: " + ", ".join(undeclared))
        for item in files:
            if item.archive_path not in available:
                raise ValueError(f"backup member is missing: {item.archive_path}")
            size, digest = _member_hash(archive, item.archive_path)
            if size != item.size or digest != item.sha256:
                raise ValueError(f"backup checksum mismatch: {item.archive_path}")


def target_path_for(
    item: ManifestFile, project_root: Path, app_data_dir: Path, *,
    external_root: Path | None = None, allow_external_targets: bool = False,
) -> Path:
    relative = _safe_relative(item.relative_path)
    if item.group == "project":
        root = project_root.resolve()
    elif item.group == "app_data":
        root = app_data_dir.resolve()
    elif item.group == "reports":
        root = (project_root / "reports").resolve()
    elif external_root is not None:
        root = external_root.resolve()
    else:
        if not allow_external_targets:
            raise ValueError(
                "backup contains external targets; use --external-root for a sandbox or "
                "--allow-external-targets to restore original paths"
            )
        original = Path(item.original_path).expanduser()
        if not original.is_absolute():
            raise ValueError(f"invalid original external path: {item.original_path!r}")
        return original.resolve()
    target = (root / relative).resolve()
    if not _inside(target, root):
        raise ValueError(f"restore target escapes its root: {target}")
    return target


def restore_plan(
    archive_path: Path, project_root: Path, app_data_dir: Path, *,
    external_root: Path | None = None, allow_external_targets: bool = False,
) -> tuple[dict[str, Any], list[tuple[ManifestFile, Path]]]:
    manifest, files = read_manifest(archive_path)
    verify_archive(archive_path, files)
    return manifest, [
        (item, target_path_for(
            item, project_root, app_data_dir, external_root=external_root,
            allow_external_targets=allow_external_targets,
        )) for item in files
    ]


def _write_member(archive: zipfile.ZipFile, member: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=target.parent) as stream:
        with archive.open(member) as source:
            shutil.copyfileobj(source, stream, length=1024 * 1024)
        temporary = Path(stream.name)
    temporary.replace(target)


def restore_backup(
    archive_path: Path, *, project_root: Path = PROJECT_ROOT,
    app_data_dir: Path | None = None, external_root: Path | None = None,
    dry_run: bool = True, allow_external_targets: bool = False,
    create_pre_restore_backup: bool = True,
) -> dict[str, Any]:
    archive_path = Path(archive_path).expanduser().resolve()
    project_root = Path(project_root).resolve()
    app_data_dir = Path(app_data_dir or app.app_data_dir()).resolve()
    started = time.monotonic()
    manifest, plan = restore_plan(
        archive_path, project_root, app_data_dir, external_root=external_root,
        allow_external_targets=allow_external_targets,
    )
    states = [
        (item, target, "unchanged" if target.is_file()
         and target.stat().st_size == item.size and sha256_file(target) == item.sha256 else "write")
        for item, target in plan
    ]
    pre_restore = ""
    if not dry_run:
        if create_pre_restore_backup:
            pre_restore = create_backup(project_root=project_root, app_data_dir=app_data_dir)["archive"]
        with zipfile.ZipFile(archive_path) as archive:
            for item, target in plan:
                _write_member(archive, item.archive_path, target)
        for item, target in plan:
            if target.stat().st_size != item.size or sha256_file(target) != item.sha256:
                raise RuntimeError(f"restored file failed verification: {target}")
    changed = sum(state == "write" for _, _, state in states)
    result = {
        "status": "dry-run" if dry_run else "completed", "archive": str(archive_path),
        "source_version": str(manifest.get("avachin_version") or ""),
        "source_commit": str(manifest.get("git_commit") or ""),
        "target_project_root": str(project_root), "target_app_data_dir": str(app_data_dir),
        "files": len(plan), "changed_files": changed,
        "unchanged_files": len(plan) - changed, "pre_restore_archive": pre_restore,
        "duration_seconds": round(time.monotonic() - started, 3),
        "targets": [
            {"group": item.group, "archive_path": item.archive_path,
             "target_path": str(target),
             "status": "restored" if not dry_run and state == "write" else state}
            for item, target, state in states
        ],
    }
    report = archive_path.with_name(
        archive_path.stem + ("-restore-dry-run.json" if dry_run else "-restore-report.json")
    )
    _atomic_json(report, result)
    result["report"] = str(report)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Back up or safely restore Avachin project and local state.")
    commands = root.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create one ZIP snapshot of project, config, databases and reports.")
    backup.add_argument("--output")
    backup.add_argument("--project-root", default=str(PROJECT_ROOT))
    backup.add_argument("--app-data-dir")
    backup.add_argument("--no-reports", action="store_true")
    restore = commands.add_parser("restore", help="Validate or restore an Avachin backup archive.")
    restore.add_argument("archive")
    restore.add_argument("--project-root", default=str(PROJECT_ROOT))
    restore.add_argument("--app-data-dir")
    restore.add_argument("--external-root")
    mode = restore.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate only; this is the default.")
    mode.add_argument("--apply", action="store_true")
    restore.add_argument("--allow-external-targets", action="store_true")
    restore.add_argument("--skip-pre-restore-backup", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "backup":
            result = create_backup(
                project_root=Path(args.project_root),
                app_data_dir=Path(args.app_data_dir).expanduser() if args.app_data_dir else None,
                output_path=Path(args.output).expanduser() if args.output else None,
                include_reports=not args.no_reports,
            )
        else:
            result = restore_backup(
                Path(args.archive), project_root=Path(args.project_root),
                app_data_dir=Path(args.app_data_dir).expanduser() if args.app_data_dir else None,
                external_root=Path(args.external_root).expanduser() if args.external_root else None,
                dry_run=not args.apply, allow_external_targets=args.allow_external_targets,
                create_pre_restore_backup=not args.skip_pre_restore_backup,
            )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
