# Avachin backup and restore

Avachin v12.5 provides a single versioned ZIP snapshot for the repository state and machine-local data required to recover the application.

## What is included

- Git-tracked project files and `config.local.json` when present.
- The complete Avachin application-data directory, including the fingerprint database and provider-usage ledger.
- Reports under `reports/`.
- A custom AudD budget database when `audd_request_budget_db_path` points outside the project and application-data directories.
- Version, Git commit, source paths, file sizes, and SHA-256 checksums in `backup-manifest.json`.

SQLite files are copied with SQLite's online backup API. WAL, SHM, and journal sidecars are not copied separately. Existing backup archives under the application-data `backups/` directory are excluded to prevent recursive backups.

## Create a backup

```powershell
py tools\avachin_backup.py backup
```

The default destination is:

```text
%LOCALAPPDATA%\SmartMusicOrganizer\backups\avachin-backup-YYYYMMDD-HHMMSS.zip
```

Choose another ZIP path when needed:

```powershell
py tools\avachin_backup.py backup --output "D:\Avachin Backups\avachin-safe.zip"
```

A JSON summary is written next to the ZIP. On Windows, `scripts\windows\backup.bat` runs the same command.

## Validate a restore

Restore is dry-run by default. It verifies the manifest, rejects unsafe or undeclared ZIP members, recalculates every checksum, resolves all target paths, and reports which files would change.

```powershell
py tools\avachin_backup.py restore "D:\Avachin Backups\avachin-safe.zip"
```

Equivalent explicit form:

```powershell
py tools\avachin_backup.py restore "D:\Avachin Backups\avachin-safe.zip" --dry-run
```

The Windows launcher is:

```powershell
scripts\windows\restore_dry_run.bat "D:\Avachin Backups\avachin-safe.zip"
```

No target file is written in dry-run mode.

## Prove restore in a sandbox

```powershell
py tools\avachin_backup.py restore "D:\Avachin Backups\avachin-safe.zip" `
  --project-root "D:\Avachin Restore Test\project" `
  --app-data-dir "D:\Avachin Restore Test\app-data" `
  --external-root "D:\Avachin Restore Test\external" `
  --apply `
  --skip-pre-restore-backup
```

After extraction, the runner verifies the size and SHA-256 checksum of every restored file. `--external-root` redirects any machine-specific external database into the sandbox.

## Apply to the live installation

First run dry-run and inspect its JSON report. Apply only when the archive and targets are correct:

```powershell
py tools\avachin_backup.py restore "D:\Avachin Backups\avachin-safe.zip" `
  --apply `
  --allow-external-targets
```

Before writing, Avachin creates a new pre-restore backup of the current installation. Files are replaced atomically and then verified. Extra files that are not present in the archive are not deleted.

Use `--allow-external-targets` only when the archive contains a configured database outside the normal project/application-data roots and restoring its original absolute path is intended. Otherwise use `--external-root` for a sandbox.

## Failure behavior

Restore stops before writing when the archive is malformed, a path attempts traversal, a payload member is undeclared or duplicated, a checksum differs, or an external target has not been explicitly authorized. A failed SQLite snapshot or filesystem write returns a nonzero exit code and a machine-readable error object.
