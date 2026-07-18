# Avachin architecture

## Public runtimes

`tools/avachin_runtime.py` is the canonical organizer entry point. It loads the complete runtime stack and sets the public version from `tools/version.py`.

`tools/avachin_bulk_index.py` is the canonical bulk fingerprint-index entry point. It enables fail-safe temporary audio repair before delegating to the bulk indexer.

`tools/avachin_status.py` is the machine-readable diagnostics boundary for desktop, mobile-facing adapters, and packaging. It returns a versioned JSON document and never returns provider credentials.

`tools/avachin_operation.py` is the stable frontend execution facade. Its larger subprocess implementation lives in `tools/_avachin_operation_core.py`; the facade normalizes terminal summaries into accurate versioned events and prevents zero-valued counters from becoming false warning/error events.

`tools/run_acceptance.py` is the stable acceptance facade. It consumes the versioned manifest under `tests/acceptance/`, runs each scenario in isolated Python processes, protects declared fixture paths by hash and size, and writes machine-readable JSON/CSV reports.

`tools/avachin_backup.py` is the P0-01 recovery boundary. It creates a versioned ZIP snapshot of project files, local configuration, application-data databases, reports, and configured external state. Restore validates paths and checksums before resolving any write target and is dry-run unless `--apply` is explicit.

Internal feature launchers remain separate so each behavior can be tested and rolled back independently:

```text
avachin_launcher.py
  -> avachin_local_first_launcher.py
    -> avachin_online_auto_learn_launcher.py
      -> avachin_audd_budget_launcher.py
        -> avachin_partial_fingerprint_launcher.py
          -> avachin_detection_launcher.py
            -> avachin_runtime.py
```

The Detection launcher is the outer compatibility layer. It does not replace the existing resolver; it converts the final Candidate into one versioned `DetectionResult`, attaches the contract to Candidate evidence, and produces GUI-ready reports.

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

## Structured operations

The operation facade launches Preview, Apply, bulk-index Preview, or bulk-index Apply in a child process. It concurrently drains stdout and stderr, publishes JSONL events, and supports cancellation without exposing credentials.

Events include lifecycle, phase, progress, artifact, repair, summary, warning, error, cancellation, and completion records. Numeric result lines such as `Skipped: 0` and `Errors safely rolled back / failed: 0` are represented as `summary` events with `status: ok`, allowing frontends to display accurate health without parsing English text.

Detection JSON and CSV paths are printed through the existing `JSON summary:` and `CSV report:` labels. They therefore appear as ordinary versioned `artifact` events without requiring a breaking Operation API schema change.

## Identification order

1. Existing trusted metadata and local registry evidence.
2. Full-track local fingerprint match.
3. Partial or mid-song local fingerprint match.
4. Free catalog and AcoustID providers when enabled.
5. AudD only as the final acoustic fallback and only while the local budget allows it.
6. Trusted online results are learned locally for future offline recognition.
7. The final Candidate is normalized into DetectionResult confidence, evidence, and decision fields.

## Detection contract

`tools/detection_contract.py` defines the schema and exactly four decisions: `LOCAL_MATCH`, `AUTO_LEARN`, `REVIEW`, and `REJECT`.

`tools/confidence.py` calculates separate audio, metadata, identity, and overall confidence. Missing acoustic evidence remains `null`. Fractional provider scores are normalized to the public `0..100` scale.

`tools/identity_resolver.py` extracts stable evidence from the legacy Candidate and input audio: provider, match mode, fingerprint score, segment coverage, offset, runner-up margin, metadata agreement, consensus, and external recording identifiers.

`tools/learning_policy.py` owns the conservative decision thresholds. A partial match without a measurable candidate margin cannot become `LOCAL_MATCH`. An online result normally becomes `AUTO_LEARN` only after successful local learning; otherwise it remains `REVIEW` unless it only enriches an already reliable local identity.

`tools/detection_report.py` preserves the original organizer CSV and writes nested JSON plus flat CSV reports. Contract fields are also stored under `candidate.evidence`, so Apply journals retain the exact decision used during the run.

The v12.6 contract is observational. It calculates `safe_to_apply` but does not yet override the legacy Apply execution path. Enforcement belongs after benchmark thresholds and Review/Undo flows are proven.

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

## Backup and restore safety

The backup archive has a versioned `backup-manifest.json`. Every payload entry records its logical group, relative path, original external path when relevant, byte size, and SHA-256 checksum. Project code comes from Git-tracked files with a conservative fallback when Git is unavailable; `config.local.json` is included explicitly.

SQLite databases are materialized through SQLite's online backup API, so a live WAL database becomes one consistent database image. WAL, SHM, journal files, and previous backup archives are excluded from the payload.

Restore performs these gates before writing:

1. Validate the manifest schema and supported groups.
2. Reject absolute paths, traversal, duplicate members, mismatched group paths, and undeclared payload members.
3. Recalculate the size and SHA-256 of every ZIP member.
4. Resolve targets below the selected project, application-data, reports, or Sandbox external root.
5. Require explicit authorization before restoring an original absolute external target.

Dry-run writes only a JSON plan. Apply creates a pre-restore backup, writes each file through a temporary sibling followed by atomic replacement, and verifies the restored checksum. Extra target files are not deleted. The complete operating procedure is documented in `docs/BACKUP_RESTORE.md`.

## Acceptance baseline

The acceptance manifest maps independent regression tests into product-level scenarios for Unknown/local-first resolution, recording identity, online-to-offline learning, partial fingerprinting, bulk indexing and duplicate handling, AudD budget protection, temporary repair, status output, operation events, backup/restore recovery, and DetectionResult decisions/reports.

Each test file runs in its own subprocess. This preserves the existing CI isolation guarantee and prevents monkey-patches or module state from leaking between scenarios. Reports include Avachin version, Git commit, Python/platform details, scenario timing, exit codes, captured output, missing fixture paths, and protected-file mutations.

Public CI fixtures are generated or mocked. Real Windows audio fixtures remain machine-local and can be attached through a local manifest that declares `required_paths` and `protected_paths` without committing copyrighted audio or credentials.

## Configuration boundaries

`config.json` contains normal application behavior. `config.local.json` overlays machine-specific settings and credentials. Environment variables can override provider credentials without changing tracked files.

The configuration model is intentionally JSON-compatible so future desktop and mobile interfaces can edit settings without importing the organizer internals.
