# Avachin

Avachin is a local-first music organizer for Windows-focused MP3 libraries. It identifies uncertain tracks, normalizes artist/album structure, learns trusted acoustic fingerprints locally, and uses online services only when local evidence is insufficient.

## Safety guarantees

- Preview is the default mode.
- Original music files are never modified during fingerprint indexing or temporary audio repair.
- Apply uses crash-safe operations, reports, and undo manifests.
- Decoder-damaged audio is repaired only as a validated temporary analysis copy.
- AudD requests are protected by a persistent local request budget.
- A failure for one file does not stop processing the remaining library.

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

Repeatable acceptance baseline:

```powershell
py tools\run_acceptance.py
```

The P5-08 runner executes the local-first, recording schema, online-to-offline learning, partial fingerprint, bulk index, duplicate, AudD budget, audio repair, status, operation, and public-entrypoint scenarios in isolated Python processes. It writes `acceptance-report.json` and `acceptance-report.csv` under `reports/acceptance/` and can fail a scenario when a protected fixture changes hash or size.

Windows launchers are available in `scripts/windows/`:

- `run_preview.bat`
- `run_apply.bat`
- `preview_local_index.bat`
- `apply_local_index.bat`
- `status.bat`
- `audd_quota_status.bat`
- `run_acceptance.bat`

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
tools/                       Runtime layers, fingerprint storage, repair, diagnostics
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

The public version is stored only in `tools/version.py`. Avachin v12.4 adds the P5-08 repeatable acceptance corpus and one-command JSON/CSV reporting baseline.
