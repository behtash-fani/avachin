# Avachin acceptance corpus

This directory is Avachin's repeatable acceptance baseline. The manifest groups the regression tests that represent real product paths: Unknown/local-first resolution, recording schema, online-to-offline learning, partial fingerprinting, bulk indexing and duplicates, AudD budget safety, temporary audio repair, runtime status, structured operations, backup/restore recovery, explainable DetectionResult decisions, official benchmark scoring, and canonical entry points.

Run all scenarios from the repository root:

```powershell
py tools\run_acceptance.py
```

Reports are written to:

```text
reports/acceptance/acceptance-report.json
reports/acceptance/acceptance-report.csv
```

Useful commands:

```powershell
py tools\run_acceptance.py --list
py tools\run_acceptance.py --scenario partial-mid-song
py tools\run_acceptance.py --scenario audio-repair-no-original-change
py tools\run_acceptance.py --scenario backup-restore-sandbox
py tools\run_acceptance.py --scenario explainable-detection-contract
py tools\run_acceptance.py --scenario official-benchmark-framework
```

## Fixture policy

Committed acceptance tests generate isolated temporary fixtures or use mocks, so CI does not need copyrighted audio or provider credentials. Machine-local real audio can be placed under `tests/acceptance/fixtures/local/` and referenced from a machine-local manifest copy. Do not commit provider tokens, personal library paths, or copyrighted recordings.

A scenario may declare `required_paths` and `protected_paths`:

- Missing paths fail required scenarios.
- Missing paths skip optional scenarios unless `--strict-optional` is used.
- Any hash/size change under a protected path fails the scenario.

This lets Windows validation protect real source MP3 files while keeping the public corpus deterministic and license-safe. The recovery scenario creates a temporary project, config, report and live SQLite database, validates dry-run, restores them into an isolated sandbox, and verifies the recovered database content. The detection scenario validates confidence separation, four-way decisions, Candidate evidence attachment, compatibility with the legacy CSV, and the nested/flat detection artifacts used by future Review UI.

The official benchmark scenario validates the complete P5 framework without copyrighted audio: read-only SQLite bootstrap, source-file preservation, deterministic sample IDs and seeded transforms, stable Recording identity for Live/Studio hard negatives, query-time capture, Precision/Recall and False Auto-Apply metrics, CLI planning/evaluation, and threshold calibration that may select only profiles with zero False Auto-Apply.
