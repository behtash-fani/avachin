# Avachin benchmark corpus

This directory contains the public schema and workflow for P5-01 through P5-05. Real music references, generated audio, local manifests, and benchmark outputs are machine-local and must not be committed.

## Recommended: one-command pipeline

On Windows, run:

```powershell
scripts\windows\run_full_benchmark.bat
```

Equivalent Python command:

```powershell
py tools\run_benchmark_pipeline.py
```

The first run automatically creates `benchmark/manifest.json` from the local fingerprint database when the manifest does not exist. It copies up to 100 trusted MP3 references into `benchmark/references/local/`; original library files are never moved, renamed, retagged, or modified.

The pipeline then:

1. validates stable Recording identities and hard-negative groups;
2. creates a unique transformed sample directory;
3. runs only `organizer-preview`;
4. runs offline by default, so AudD budget is not consumed;
5. captures structured Operation events and DetectionResult artifacts;
6. calculates Precision, Recall, Unknown/Review/Reject, query time, hard-negative confusion, and False Auto-Apply;
7. searches 3,528 bounded threshold profiles and retains only zero-False-Auto-Apply profiles;
8. writes a self-contained run directory under `reports/benchmark/`.

A successful run returns exit code `0`. Exit code `2` means Preview and evaluation completed, but the zero-False-Auto-Apply gate failed. Reports are still preserved for diagnosis and threshold review.

To deliberately rebuild references and replace the local manifest:

```powershell
py tools\run_benchmark_pipeline.py --refresh-corpus --limit 100
```

Online providers require explicit opt-in:

```powershell
py tools\run_benchmark_pipeline.py --allow-online
```

Do not enable online mode for the official local-recognition release gate unless the purpose of the run is specifically to measure provider fallback.

Each run directory contains:

```text
manifest.snapshot.json
generated-manifest.json
operation-events.jsonl
detection-report.json
detection-report.csv
benchmark-report.json
benchmark-report.csv
threshold-profile.json
pipeline-report.json
```

The generated threshold profile is evidence only. It never rewrites `config.json` or `config.local.json` automatically.

## Manual workflow

### 1. Create the local manifest

Bootstrap from the read-only fingerprint database:

```powershell
py tools\avachin_benchmark.py bootstrap --limit 100
```

Or copy the example:

```powershell
Copy-Item benchmark\manifest.example.json benchmark\manifest.json
```

For every trusted Recording, set:

- a stable `recording_id`;
- a relative source path under `benchmark/`;
- verified title, artist, duration, split, and version;
- at least one stable identity such as the Avachin Recording ID, ISRC, or MusicBrainz Recording ID.

For Live/Studio/Remix/Remaster pairs, use the same `hard_negative_group` and different stable identifiers. Shared text identities are treated as ambiguous and are excluded from correctness scoring.

### 2. Validate and plan

```powershell
py tools\avachin_benchmark.py validate
py tools\avachin_benchmark.py generate --plan-only
```

Planning writes `benchmark/generated-manifest.json` without creating audio. Sample IDs and noise seeds are deterministic.

### 3. Generate transformed audio

```powershell
py tools\avachin_benchmark.py generate
```

Supported transforms:

- clean identity copy;
- middle/start/end clips, including 5, 10, and 15 seconds;
- MP3 bitrate variants;
- head/tail trim;
- leading silence;
- deterministic colored noise;
- volume changes.

FFmpeg is required only for non-identity transforms. References and generated files remain under the selected corpus root.

### 4. Run Avachin Preview

Run Preview on the generated directory and keep the emitted `detection-report.json` artifact:

```powershell
py tools\avachin_operation.py organizer-preview --root "C:\path\to\avachin\benchmark\generated" --offline
```

Do not use Apply for benchmark samples.

### 5. Evaluate

```powershell
py tools\avachin_benchmark.py evaluate `
  --detection-report "C:\path\to\detection-report.json" `
  --corpus-root "C:\path\to\avachin\benchmark"
```

The report records Avachin version, Git commit, configuration, per-sample evidence, per-transform metrics, and official summary metrics:

- Precision and Recall;
- Unknown, Review, and Reject rates;
- Auto-Apply precision and recall;
- False Auto-Apply count and rate;
- Hard-negative confusions;
- query-time mean, p50, and p95.

The release gate is strict:

```text
False Auto-Apply = 0
```

A nonzero value makes evaluation fail while keeping the report.

### 6. Calibrate thresholds

```powershell
py tools\avachin_benchmark.py calibrate
```

Calibration searches identity, audio, metadata, partial-margin, and Review thresholds. It first filters to profiles with zero False Auto-Apply, then selects the profile with the highest correct Auto-Apply coverage.

The generated profile is evidence, not an automatic configuration write. Thresholds should be promoted to normal configuration only after the validation corpus is representative and the report has been reviewed.
