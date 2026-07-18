# Avachin benchmark corpus

This directory contains the public schema and workflow for P5-01 through P5-05. Real music references, generated audio, local manifests, and benchmark outputs are machine-local and must not be committed.

## 1. Create the local manifest

Copy the example:

```powershell
Copy-Item benchmark\manifest.example.json benchmark\manifest.json
```

For every trusted Recording, set:

- a stable `recording_id`;
- a relative source path under `benchmark/`;
- verified title, artist, duration, split, and version;
- at least one stable identity such as the Avachin Recording ID, ISRC, or MusicBrainz Recording ID.

For Live/Studio/Remix/Remaster pairs, use the same `hard_negative_group` and different stable identifiers. Shared text identities are treated as ambiguous and are excluded from correctness scoring.

## 2. Validate and plan

```powershell
py tools\avachin_benchmark.py validate
py tools\avachin_benchmark.py generate --plan-only
```

Planning writes `benchmark/generated-manifest.json` without creating audio. Sample IDs and noise seeds are deterministic.

## 3. Generate transformed audio

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

## 4. Run Avachin Preview

Run Preview on the generated directory and keep the emitted `detection-report.json` artifact:

```powershell
py tools\avachin_operation.py organizer-preview --root "C:\path\to\avachin\benchmark\generated"
```

Do not use Apply for benchmark samples.

## 5. Evaluate

```powershell
py tools\avachin_benchmark.py evaluate `
  --detection-report "C:\path\to\detection-report.json" `
  --corpus-root "C:\path\to\avachin\benchmark"
```

Outputs:

```text
reports/benchmark/benchmark-report.json
reports/benchmark/benchmark-report.csv
```

The report records Avachin version, Git commit, configuration, per-sample evidence, per-transform metrics, and official summary metrics:

- Precision and Recall;
- Unknown, Review, and Reject rates;
- Auto-Apply precision and recall;
- False Auto-Apply count and rate;
- Hard-negative confusions;
- query-time mean, p50, and p95 when timings are available.

The release gate is strict:

```text
False Auto-Apply = 0
```

A nonzero value makes the `evaluate` command return a failing status.

## 6. Calibrate thresholds

```powershell
py tools\avachin_benchmark.py calibrate
```

Calibration searches identity, audio, metadata, partial-margin, and Review thresholds. It first filters to profiles with zero False Auto-Apply, then selects the profile with the highest correct Auto-Apply coverage.

Output:

```text
reports/benchmark/threshold-profile.json
```

The generated profile is evidence, not an automatic configuration write. Thresholds should be promoted to normal configuration only after the validation corpus is representative and the report has been reviewed.
