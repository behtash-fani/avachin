# Avachin

Avachin is a local-first music organizer for Windows-focused MP3 libraries. It identifies uncertain tracks, normalizes artist/album structure, learns trusted acoustic fingerprints locally, and uses online services only when local evidence is insufficient.

## Safety guarantees

- Preview is the default mode.
- Original music files are never modified during fingerprint indexing, benchmark bootstrap, transforms, or temporary audio repair.
- Apply uses crash-safe operations, reports, and undo manifests.
- Decoder-damaged audio is repaired only as a validated temporary analysis copy.
- AudD requests are protected by a persistent local request budget.
- A failure for one file does not stop processing the remaining library.
- Restore is dry-run by default and validates every manifest path and checksum before writing.
- Every MP3 receives one explainable `LOCAL_MATCH`, `AUTO_LEARN`, `REVIEW`, or `REJECT` decision.
- Benchmark release thresholds must keep `False Auto-Apply = 0` on the reviewed validation corpus.

## Canonical entry points

Use these public entry points from scripts, future GUI code, and packaging:

```powershell
py tools\avachin_runtime.py
py tools\avachin_runtime.py --apply
py tools\avachin_bulk_index.py --root "C:\Users\name\Music"
py tools\avachin_bulk_index.py --root "C:\Users\name\Music" --apply
```

Machine-readable runtime status:

```powershell
py tools\avachin_status.py
py tools\avachin_status.py --json
py tools\avachin_status.py --json --compact
```

Structured frontend operations:

```powershell
py tools\avachin_operation.py organizer-preview --root "C:\Music"
py tools\avachin_operation.py organizer-apply --root "C:\Music"
py tools\avachin_operation.py bulk-index-preview --root "C:\Music"
py tools\avachin_operation.py bulk-index-apply --root "C:\Music"
```

The operation API emits one versioned JSON object per line. Zero-valued summary counters are emitted as normal `summary` events rather than false warnings/errors. The implementation runs in a child process so frontend crashes, listener failures, cancellation, or one operation failure do not corrupt the frontend process.

Explainable detection reports:

```text
detection-report.json
detection-report.csv
```

Every Candidate is adapted to a versioned `DetectionResult` with separate audio, metadata, identity, and overall confidence. Evidence includes provider, fingerprint score, segment coverage, offset, candidate margin, metadata agreement, consensus, stable identifiers, decision reason, and measured per-file query time. The original `report.csv` remains compatible. See `docs/DETECTION_CONTRACT.md` for the policy and schema.

## Official benchmark

Bootstrap a reviewable local corpus from the fingerprint database, generate deterministic transforms, run Preview, evaluate the detection artifact, and calibrate conservative thresholds:

```powershell
py tools\avachin_benchmark.py bootstrap --limit 100
py tools\avachin_benchmark.py validate
py tools\avachin_benchmark.py generate --plan-only
py tools\avachin_benchmark.py generate
py tools\avachin_operation.py organizer-preview --root "benchmark\generated"
py tools\avachin_benchmark.py evaluate --detection-report "C:\path\detection-report.json" --corpus-root "benchmark"
py tools\avachin_benchmark.py calibrate
```

The framework supports clean references, 5/10/15-second clips, bitrate changes, trim, leading silence, seeded noise, volume changes, and explicit Live/Studio/Remix/Remaster hard negatives. Reports include Precision, Recall, Unknown/Review/Reject rates, Auto-Apply precision/recall, hard-negative confusions, query-time mean/p50/p95, and per-transform metrics. Evaluation fails when False Auto-Apply is nonzero. Real reference audio, generated files, local manifests, and reports are ignored by Git. See `benchmark/README.md`.

One-command backup and restore validation:

```powershell
py tools\avachin_backup.py backup
py tools\avachin_backup.py restore "D:\Avachin Backups\avachin-backup.zip"
```

A backup is a versioned ZIP containing the Git-tracked project state, local config, application-data databases, reports, and any configured external AudD ledger. SQLite databases are captured through the online backup API. Restore is dry-run by default; `--apply` creates a pre-restore backup, writes atomically, and verifies each restored SHA-256 checksum. See `docs/BACKUP_RESTORE.md` for the complete runbook and Sandbox procedure.

Repeatable acceptance baseline:

```powershell
py tools\run_acceptance.py
```

The acceptance runner executes local-first, recording schema, online-to-offline learning, partial fingerprint, bulk index, duplicate, AudD budget, audio repair, status, operation, backup/restore, DetectionResult, official benchmark, and public-entrypoint scenarios in isolated Python processes. It writes `acceptance-report.json` and `acceptance-report.csv` under `reports/acceptance/` and can fail a scenario when a protected fixture changes hash or size.

Windows launchers are available in `scripts/windows/`:

- `run_preview.bat`
- `run_apply.bat`
- `preview_local_index.bat`
- `apply_local_index.bat`
- `status.bat`
- `audd_quota_status.bat`
- `run_acceptance.bat`
- `backup.bat`
- `restore_dry_run.bat`
- `benchmark.bat`

The older `avachin_*_launcher.py` files are internal feature layers retained for compatibility. New callers should use the canonical entry points above.

## Output layout

Albums:

```text
Artist / Album / Title - Artist.mp3
```

Singles:

```text
Artist / Singles / Title - Artist.mp3
```

## Configuration

- `config.json`: normal organizer settings.
- `config.local.json`: private/local overrides and provider credentials; not committed.
- `config.example.json`: base configuration example.
- `config.local.example.json`: local-first, online fallback, repair, and request-budget example.

## Repository layout

```text
smart_music_organizer.py     Core organizer engine
tools/                       Runtime, detection, benchmark, fingerprint, recovery, repair and diagnostics
benchmark/                   Public benchmark schema, workflow and local-only corpus boundary
scripts/windows/             User-facing Windows launchers
reference_data/              Curated artist and track registries
tests/                       Regression and acceptance tests
.github/workflows/           Continuous integration
```

See `docs/ARCHITECTURE.md` for runtime and data-flow details.

## Development checks

```powershell
py -m compileall -q smart_music_organizer.py configure.py tools tests
Get-ChildItem tests\test_*.py | ForEach-Object { py $_.FullName }
py tools\run_acceptance.py
```

All tests run in isolated Python processes in CI to prevent runtime monkey-patch state from leaking between test modules. The acceptance reports are uploaded as a CI artifact even when a scenario fails.

## Current version

The public version is stored only in `tools/version.py`. Avachin v12.7 adds the official local benchmark framework, deterministic audio transforms, Recording-aware hard-negative scoring, per-file query timing, and zero-False-Auto-Apply threshold calibration.
