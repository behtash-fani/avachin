# Benchmark reference review and quarantine

Avachin keeps benchmark audio and review decisions local. A reference that is
confirmed to contain the wrong audio must not be deleted silently and must not
remain in the release gate. It is recorded in `benchmark/review.json` with the
manifest identity, confirmed audio identity, reason, reviewer and timestamp.

The review ledger is ignored by Git because it describes the owner's local
corpus. Quarantine never modifies the source MP3, local fingerprint database or
previous raw benchmark artifacts.

## Quarantine a confirmed contaminated reference

```powershell
scripts\windows\review_benchmark.bat quarantine `
  --recording-id rec_bd10bf080fefc561f466ced8811ec731 `
  --reason "Manifest says Alan Walker - Faded, but playback confirms Shahrokh - Pedar" `
  --confirmed-artist "Shahrokh" `
  --confirmed-title "Pedar"
```

## Re-score the newest completed run

```powershell
scripts\windows\review_benchmark.bat reanalyze
```

This command does not call FFmpeg, regenerate transformed MP3s, run Preview or
consume an online-provider budget. It reads the saved manifest, generated
manifest and DetectionResult report, excludes only explicitly quarantined
recordings and writes:

```text
benchmark-reviewed-report.json
benchmark-reviewed-report.csv
threshold-reviewed-profile.json
pipeline-reviewed-report.json
```

A reviewed run passes only when the included corpus has zero False Auto-Apply.
Every excluded recording and sample count remains visible in the reports.

## Inspect or undo local review decisions

```powershell
scripts\windows\review_benchmark.bat list
scripts\windows\review_benchmark.bat restore --recording-id <RECORDING_ID>
```

Automatic quarantine is intentionally forbidden. A systematic mismatch may be
reported as suspicious, but excluding a reference requires an explicit human
confirmation so a real recognition regression cannot be hidden from the gate.
