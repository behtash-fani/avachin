# Avachin architecture

## Public runtimes

`tools/avachin_runtime.py` is the canonical organizer entry point. It loads the complete runtime stack and sets the public version from `tools/version.py`.

`tools/avachin_bulk_index.py` is the canonical bulk fingerprint-index entry point. It enables fail-safe temporary audio repair before delegating to the bulk indexer.

`tools/avachin_status.py` is the machine-readable diagnostics boundary for desktop, mobile-facing adapters, and packaging. It returns a versioned JSON document and never returns provider credentials.

Internal feature launchers remain separate so each behavior can be tested and rolled back independently:

```text
avachin_launcher.py
  -> avachin_local_first_launcher.py
    -> avachin_online_auto_learn_launcher.py
      -> avachin_audd_budget_launcher.py
        -> avachin_partial_fingerprint_launcher.py
          -> avachin_runtime.py
```

These internal names are implementation details. GUI, mobile-facing adapters, packaging, and Windows scripts should call only the canonical runtimes.

## Status and diagnostics

The status API is safe to call before an operation starts. It exposes:

- public Avachin version and status-schema version;
- Python, `fpcalc`, and FFmpeg availability;
- provider enabled/configured booleans without credential values;
- fingerprint database schema and row counts;
- AudD budget usage and remaining requests;
- readiness flags and non-fatal warnings.

Existing fingerprint and provider-usage databases are opened in SQLite read-only mode. A status check does not create, migrate, or update either database.

## Identification order

1. Existing trusted metadata and local registry evidence.
2. Full-track local fingerprint match.
3. Partial or mid-song local fingerprint match.
4. Free catalog and AcoustID providers when enabled.
5. AudD only as the final acoustic fallback and only while the local budget allows it.
6. Trusted online results are learned locally for future offline recognition.

## Local fingerprint storage

The SQLite database lives outside the music library under the application data directory.

- Schema V2 separates recordings, physical audio files, fingerprints, and external provider IDs.
- Schema V3 adds overlapping fingerprint segments for clips and mid-song recognition.
- Bulk indexing creates a timestamped SQLite backup before writes.
- The database stores fingerprints and metadata, never audio content.

## Fail-safe audio repair

When `fpcalc` reports a decoder-related failure:

1. The original file remains read-only.
2. FFmpeg writes a re-encoded copy to an isolated temporary directory.
3. The temporary copy is fully decoded for validation.
4. Only a validated copy is used for fingerprint calculation.
5. The temporary directory is removed unless explicitly retained for diagnostics.
6. Any repair failure is attached to that file only; processing continues.

Repair publishes structured events for future GUI progress views. Listener errors are isolated from the processing pipeline.

## Apply safety

The organizer identifies and plans the complete run before changing the library. Apply operations use a journal, avoid overwriting existing files, produce reports, and write an undo manifest outside the selected music folder.

## Configuration boundaries

`config.json` contains normal application behavior. `config.local.json` overlays machine-specific settings and credentials. Environment variables can override provider credentials without changing tracked files.

The configuration model is intentionally JSON-compatible so future desktop and mobile interfaces can edit settings without importing the organizer internals.
