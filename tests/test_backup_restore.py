#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import avachin_backup as backup  # noqa: E402


class BackupRestoreTests(unittest.TestCase):
    def make_project(self, root: Path) -> tuple[Path, Path]:
        project = root / "project"
        app_data = root / "app-data"
        (project / "tools").mkdir(parents=True)
        (project / "reports").mkdir()
        app_data.mkdir()
        (project / "README.md").write_text("Avachin test\n", encoding="utf-8")
        (project / "config.json").write_text('{"offline": true}', encoding="utf-8")
        (project / "config.local.json").write_text('{"audd_api_token": "private"}', encoding="utf-8")
        (project / "tools" / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        (project / "reports" / "summary.json").write_text('{"ok": true}', encoding="utf-8")
        db = app_data / "local_fingerprint_library.sqlite3"
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE recordings (id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("INSERT INTO recordings(title) VALUES ('Pedar')")
            conn.commit()
        finally:
            conn.close()
        return project, app_data

    def test_backup_and_restore_into_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, app_data = self.make_project(root)
            archive = root / "backup.zip"
            with mock.patch.object(backup, "_git_tracked_files", return_value=[]):
                created = backup.create_backup(
                    project_root=project,
                    app_data_dir=app_data,
                    output_path=archive,
                )
            self.assertEqual(created["status"], "completed")
            self.assertTrue(archive.is_file())
            manifest, files = backup.read_manifest(archive)
            self.assertEqual(manifest["schema_version"], 1)
            self.assertTrue(any(item.group == "app_data" for item in files))
            backup.verify_archive(archive, files)

            sandbox_project = root / "sandbox-project"
            sandbox_app_data = root / "sandbox-app-data"
            dry_run = backup.restore_backup(
                archive,
                project_root=sandbox_project,
                app_data_dir=sandbox_app_data,
                dry_run=True,
            )
            self.assertEqual(dry_run["status"], "dry-run")
            self.assertFalse((sandbox_project / "README.md").exists())

            restored = backup.restore_backup(
                archive,
                project_root=sandbox_project,
                app_data_dir=sandbox_app_data,
                dry_run=False,
                create_pre_restore_backup=False,
            )
            self.assertEqual(restored["status"], "completed")
            self.assertEqual((sandbox_project / "README.md").read_text(encoding="utf-8"), "Avachin test\n")
            self.assertEqual(
                json.loads((sandbox_project / "config.local.json").read_text(encoding="utf-8"))["audd_api_token"],
                "private",
            )
            conn = sqlite3.connect(sandbox_app_data / "local_fingerprint_library.sqlite3")
            try:
                title = conn.execute("SELECT title FROM recordings").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(title, "Pedar")

    def test_tampered_archive_fails_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, app_data = self.make_project(root)
            archive = root / "backup.zip"
            with mock.patch.object(backup, "_git_tracked_files", return_value=[]):
                backup.create_backup(project_root=project, app_data_dir=app_data, output_path=archive)
            _, files = backup.read_manifest(archive)
            first = files[0]
            tampered = root / "tampered.zip"
            with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(tampered, "w") as target:
                for name in source.namelist():
                    data = source.read(name)
                    if name == first.archive_path:
                        data += b"tampered"
                    target.writestr(name, data)
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                backup.verify_archive(tampered, files)

    def test_manifest_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "bad.zip"
            manifest = {
                "schema_version": 1,
                "files": [
                    {
                        "group": "project",
                        "relative_path": "../escape.txt",
                        "archive_path": "payload/project/../escape.txt",
                        "size": 0,
                        "sha256": "0" * 64,
                    }
                ],
            }
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr(backup.MANIFEST_NAME, json.dumps(manifest))
                stream.writestr("payload/escape.txt", b"")
            with self.assertRaisesRegex(ValueError, "unsafe archive-relative path"):
                backup.read_manifest(archive)

    def test_backup_excludes_previous_backups_and_sqlite_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, app_data = self.make_project(root)
            backups = app_data / backup.DEFAULT_BACKUP_DIRNAME
            backups.mkdir()
            (backups / "old.zip").write_bytes(b"old")
            (app_data / "local_fingerprint_library.sqlite3-wal").write_bytes(b"wal")
            archive = backups / "current.zip"
            with mock.patch.object(backup, "_git_tracked_files", return_value=[]):
                backup.create_backup(
                    project_root=project,
                    app_data_dir=app_data,
                    output_path=archive,
                )
            _, files = backup.read_manifest(archive)
            archived = {item.relative_path for item in files if item.group == "app_data"}
            self.assertNotIn("backups/old.zip", archived)
            self.assertNotIn("local_fingerprint_library.sqlite3-wal", archived)
            self.assertIn("local_fingerprint_library.sqlite3", archived)

    def test_archive_rejects_undeclared_payload_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, app_data = self.make_project(root)
            archive = root / "backup.zip"
            with mock.patch.object(backup, "_git_tracked_files", return_value=[]):
                backup.create_backup(project_root=project, app_data_dir=app_data, output_path=archive)
            _, files = backup.read_manifest(archive)
            modified = root / "extra.zip"
            with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(modified, "w") as target:
                for info in source.infolist():
                    target.writestr(info, source.read(info.filename))
                target.writestr("payload/project/undeclared.txt", b"unexpected")
            with self.assertRaisesRegex(ValueError, "undeclared payload"):
                backup.verify_archive(modified, files)

    def test_external_restore_requires_explicit_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            item = backup.ManifestFile(
                group="external",
                relative_path="provider.sqlite3",
                archive_path="payload/external/provider.sqlite3",
                size=0,
                sha256="0" * 64,
                original_path=str((root / "original-provider.sqlite3").resolve()),
            )
            with self.assertRaisesRegex(ValueError, "external targets"):
                backup.target_path_for(
                    item,
                    project_root=root / "project",
                    app_data_dir=root / "app",
                    external_root=None,
                    allow_external_targets=False,
                )
            target = backup.target_path_for(
                item,
                project_root=root / "project",
                app_data_dir=root / "app",
                external_root=root / "external",
                allow_external_targets=False,
            )
            self.assertEqual(target, (root / "external" / "provider.sqlite3").resolve())


if __name__ == "__main__":
    unittest.main()
