#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run Avachin's repeatable acceptance baseline and write JSON/CSV reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.version import AVACHIN_VERSION  # noqa: E402

MANIFEST_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
DEFAULT_MANIFEST = PROJECT_ROOT / "tests" / "acceptance" / "manifest.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "acceptance"
DEFAULT_TIMEOUT_SECONDS = 180
OUTPUT_LIMIT = 200_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _safe_text(value: str, limit: int = OUTPUT_LIMIT) -> str:
    text = str(value or "").replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_paths(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """Return a stable snapshot for files/directories without following symlinks."""

    snapshot: dict[str, dict[str, Any]] = {}
    for root in sorted({path.resolve() for path in paths}, key=lambda item: str(item).casefold()):
        if not root.exists():
            snapshot[str(root)] = {"kind": "missing"}
            continue
        candidates = [root]
        if root.is_dir():
            candidates = [item for item in root.rglob("*") if item.is_file() or item.is_symlink()]
        for item in sorted(candidates, key=lambda value: str(value).casefold()):
            key = str(item.resolve())
            if item.is_symlink():
                snapshot[key] = {"kind": "symlink", "target": os.readlink(item)}
                continue
            stat = item.stat()
            snapshot[key] = {
                "kind": "file",
                "size": stat.st_size,
                "sha256": _sha256(item),
            }
    return snapshot


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _require_string_list(raw: Any, *, field_name: str, scenario_id: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"scenario {scenario_id!r} field {field_name!r} must be a list of strings")
    return [item.strip() for item in raw]


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    title: str
    description: str
    category: str
    test_files: tuple[str, ...]
    required_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    optional: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "ScenarioSpec":
        if not isinstance(raw, dict):
            raise ValueError("each scenario must be an object")
        scenario_id = str(raw.get("id") or "").strip()
        if not scenario_id:
            raise ValueError("each scenario requires a non-empty id")
        title = str(raw.get("title") or scenario_id).strip()
        description = str(raw.get("description") or "").strip()
        category = str(raw.get("category") or "general").strip()
        test_files = _require_string_list(raw.get("test_files"), field_name="test_files", scenario_id=scenario_id)
        if not test_files:
            raise ValueError(f"scenario {scenario_id!r} must declare at least one test file")
        timeout = int(raw.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        if timeout < 1 or timeout > 3600:
            raise ValueError(f"scenario {scenario_id!r} timeout_seconds must be between 1 and 3600")
        return cls(
            scenario_id=scenario_id,
            title=title,
            description=description,
            category=category,
            test_files=tuple(test_files),
            required_paths=tuple(
                _require_string_list(raw.get("required_paths"), field_name="required_paths", scenario_id=scenario_id)
            ),
            protected_paths=tuple(
                _require_string_list(raw.get("protected_paths"), field_name="protected_paths", scenario_id=scenario_id)
            ),
            optional=bool(raw.get("optional", False)),
            timeout_seconds=timeout,
        )


@dataclass
class CommandResult:
    test_file: str
    command: list[str]
    status: str
    exit_code: int | None
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    error: str = ""


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    category: str
    status: str
    started_at: str
    duration_seconds: float
    description: str = ""
    commands: list[CommandResult] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    mutated_paths: list[str] = field(default_factory=list)
    error: str = ""


def load_manifest(path: Path) -> tuple[dict[str, Any], list[ScenarioSpec]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("acceptance manifest must be a JSON object")
    if int(payload.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported manifest schema {payload.get('schema_version')!r}; expected {MANIFEST_SCHEMA_VERSION}"
        )
    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("acceptance manifest requires a non-empty scenarios list")
    scenarios = [ScenarioSpec.from_mapping(item) for item in raw_scenarios]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for scenario in scenarios:
        if scenario.scenario_id in seen:
            duplicates.add(scenario.scenario_id)
        seen.add(scenario.scenario_id)
    if duplicates:
        raise ValueError(f"duplicate scenario ids: {', '.join(sorted(duplicates))}")
    return payload, scenarios


def _run_test_file(test_file: str, timeout_seconds: int) -> CommandResult:
    path = _resolve_project_path(test_file)
    command = [sys.executable, str(path)]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        duration = round(time.monotonic() - started, 3)
        return CommandResult(
            test_file=test_file,
            command=command,
            status="passed" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            duration_seconds=duration,
            stdout=_safe_text(completed.stdout),
            stderr=_safe_text(completed.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            test_file=test_file,
            command=command,
            status="failed",
            exit_code=None,
            duration_seconds=round(time.monotonic() - started, 3),
            stdout=_safe_text(exc.stdout or ""),
            stderr=_safe_text(exc.stderr or ""),
            error=f"timed out after {timeout_seconds} seconds",
        )
    except OSError as exc:
        return CommandResult(
            test_file=test_file,
            command=command,
            status="failed",
            exit_code=None,
            duration_seconds=round(time.monotonic() - started, 3),
            error=str(exc),
        )


def run_scenario(spec: ScenarioSpec, *, strict_optional: bool = False) -> ScenarioResult:
    started_at = utc_now()
    started = time.monotonic()
    required = [_resolve_project_path(value) for value in (*spec.test_files, *spec.required_paths)]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        status = "failed" if strict_optional or not spec.optional else "skipped"
        return ScenarioResult(
            scenario_id=spec.scenario_id,
            title=spec.title,
            category=spec.category,
            status=status,
            started_at=started_at,
            duration_seconds=round(time.monotonic() - started, 3),
            description=spec.description,
            missing_paths=missing,
            error="required acceptance paths are missing",
        )

    protected = [_resolve_project_path(value) for value in spec.protected_paths]
    before = snapshot_paths(protected)
    commands: list[CommandResult] = []
    for test_file in spec.test_files:
        command_result = _run_test_file(test_file, spec.timeout_seconds)
        commands.append(command_result)
        if command_result.status != "passed":
            break
    after = snapshot_paths(protected)
    mutated = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
    passed = all(command.status == "passed" for command in commands) and not mutated
    error = ""
    if mutated:
        error = "protected acceptance fixture changed during the scenario"
    elif not passed:
        error = "one or more acceptance test commands failed"
    return ScenarioResult(
        scenario_id=spec.scenario_id,
        title=spec.title,
        category=spec.category,
        status="passed" if passed else "failed",
        started_at=started_at,
        duration_seconds=round(time.monotonic() - started, 3),
        description=spec.description,
        commands=commands,
        mutated_paths=mutated,
        error=error,
    )


def build_report(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    results: Sequence[ScenarioResult],
    started_at: str,
    duration_seconds: float,
) -> dict[str, Any]:
    counts = {status: sum(result.status == status for result in results) for status in ("passed", "failed", "skipped")}
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "acceptance_manifest_schema": MANIFEST_SCHEMA_VERSION,
        "name": manifest.get("name", "Avachin acceptance baseline"),
        "status": "passed" if counts["failed"] == 0 else "failed",
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(duration_seconds, 3),
        "avachin_version": AVACHIN_VERSION,
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "manifest_path": str(manifest_path),
        "summary": {
            "total": len(results),
            **counts,
        },
        "scenarios": [
            {
                **{key: value for key, value in asdict(result).items() if value not in ("", [], None)},
                "commands": [
                    {key: value for key, value in asdict(command).items() if value not in ("", [], None)}
                    for command in result.commands
                ],
            }
            for result in results
        ],
    }


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False, dir=path.parent) as stream:
        stream.write(content)
        temporary = Path(stream.name)
    temporary.replace(path)


def write_reports(report: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "acceptance-report.json"
    csv_path = report_dir / "acceptance-report.csv"
    _atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    rows: list[dict[str, Any]] = []
    for scenario in report["scenarios"]:
        commands = scenario.get("commands", [])
        rows.append(
            {
                "scenario_id": scenario["scenario_id"],
                "title": scenario["title"],
                "category": scenario["category"],
                "status": scenario["status"],
                "duration_seconds": scenario["duration_seconds"],
                "commands": len(commands),
                "failed_test": next(
                    (command.get("test_file", "") for command in commands if command.get("status") == "failed"),
                    "",
                ),
                "missing_paths": " | ".join(scenario.get("missing_paths", [])),
                "mutated_paths": " | ".join(scenario.get("mutated_paths", [])),
                "error": scenario.get("error", ""),
            }
        )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False, dir=report_dir) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "scenario_id",
                "title",
                "category",
                "status",
                "duration_seconds",
                "commands",
                "failed_test",
                "missing_paths",
                "mutated_paths",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(stream.name)
    temporary.replace(csv_path)
    return json_path, csv_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Avachin's repeatable acceptance corpus and write JSON/CSV reports."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Acceptance manifest JSON path.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for acceptance reports.")
    parser.add_argument("--scenario", action="append", default=[], help="Run only this scenario id; repeatable.")
    parser.add_argument("--list", action="store_true", help="List available scenario ids without running them.")
    parser.add_argument(
        "--strict-optional",
        action="store_true",
        help="Fail instead of skip when an optional scenario's external fixture is missing.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest_path = _resolve_project_path(args.manifest)
    report_dir = _resolve_project_path(args.report_dir)
    try:
        manifest, scenarios = load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Acceptance manifest error: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for scenario in scenarios:
            marker = " optional" if scenario.optional else ""
            print(f"{scenario.scenario_id}\t{scenario.category}{marker}\t{scenario.title}")
        return 0

    selected_ids = set(args.scenario)
    if selected_ids:
        known_ids = {scenario.scenario_id for scenario in scenarios}
        unknown_ids = selected_ids - known_ids
        if unknown_ids:
            print(f"Unknown acceptance scenario(s): {', '.join(sorted(unknown_ids))}", file=sys.stderr)
            return 2
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id in selected_ids]

    started_at = utc_now()
    started = time.monotonic()
    results: list[ScenarioResult] = []
    for index, scenario in enumerate(scenarios, start=1):
        print(f"[{index}/{len(scenarios)}] {scenario.scenario_id}: {scenario.title}")
        result = run_scenario(scenario, strict_optional=args.strict_optional)
        results.append(result)
        print(f"  {result.status.upper()} ({result.duration_seconds:.3f}s)")
        if result.error:
            print(f"  {result.error}")

    report = build_report(
        manifest_path=manifest_path,
        manifest=manifest,
        results=results,
        started_at=started_at,
        duration_seconds=time.monotonic() - started,
    )
    json_path, csv_path = write_reports(report, report_dir)
    summary = report["summary"]
    print(
        "Acceptance summary: "
        f"{summary['passed']} passed, {summary['failed']} failed, {summary['skipped']} skipped"
    )
    print(f"JSON report: {json_path}")
    print(f"CSV report: {csv_path}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
