# Avachin DetectionResult contract

Avachin v12.6 converts every resolved `Candidate` into one versioned, JSON-safe `DetectionResult`. The legacy candidate and organizer behavior remain compatible while benchmark, Review UI, and future adapters consume one stable explanation model.

## Decisions

Every MP3 detection produces exactly one decision:

- `LOCAL_MATCH`: trusted local acoustic, registry, existing-tag, or local-identity evidence.
- `AUTO_LEARN`: a trusted online identity was successfully learned into the local fingerprint database.
- `REVIEW`: a plausible candidate exists but is not safe enough for automatic approval.
- `REJECT`: the identity is missing, placeholder-based, or below the review threshold.

`safe_to_apply` is true only for `LOCAL_MATCH` and `AUTO_LEARN`. `should_learn` is true only for `AUTO_LEARN`.

The first contract release is observational: it records the safe decision without changing the legacy organizer's Apply behavior. GUI Apply enforcement will be enabled only after benchmark thresholds and Review/Undo flows are validated.

## Confidence model

Confidence is separated into four fields:

- `audio`: acoustic/fingerprint evidence when available; `null` for metadata-only candidates.
- `metadata`: title, artist, duration, and exact-identifier agreement.
- `identity`: candidate confidence adjusted by provider quality, metadata agreement, and stable identifiers.
- `overall`: an explainable weighted score; acoustic evidence receives the largest weight when present.

A value in the provider's `0..1` range is normalized to `0..100`. Missing audio evidence remains `null`, not a false zero.

## Evidence

The normalized evidence contains only fields suitable for reports and frontends:

- provider and match mode;
- fingerprint score;
- segment coverage and offset;
- candidate/runner-up margin;
- title, artist, and duration agreement;
- consensus providers;
- recording-level external identifiers;
- non-secret decision flags.

Raw provider responses, credentials, and tokens are not copied into the detection report.

## Runtime integration

`tools/avachin_detection_launcher.py` is the outer runtime layer. It wraps the existing local-first/auto-learn/partial-fingerprint resolver, attaches the complete contract under `candidate.evidence["detection_result"]`, and stores short compatibility fields:

```text
detection_decision
detection_reason
detection_safe_to_apply
```

Because the candidate is already serialized into the Apply journal, the versioned contract is preserved in journal and undo evidence without changing the core `Candidate` dataclass.

A contract exception cannot stop Preview or Apply. The candidate is conservatively classified as `REVIEW` or `REJECT`, a warning is recorded, and processing continues.

## Reports and Operation API

Every organizer run keeps the original `report.csv` and additionally writes:

```text
detection-report.json
detection-report.csv
```

The JSON file preserves the nested contract. The CSV file flattens decision, confidence, fingerprint, offset, coverage, margin, identifiers, flags, and runtime status for analysis.

The runtime prints both paths using existing `JSON summary:` and `CSV report:` artifact labels, so the structured Operation API exposes them as normal `artifact` events without changing its event schema.

## Policy thresholds

The policy reuses existing runtime thresholds and supports these optional overrides:

```json
{
  "detection_local_min_confidence": 86,
  "detection_local_audio_min_confidence": 86,
  "detection_partial_min_margin": 2,
  "detection_review_min_confidence": 70
}
```

Existing `local_fingerprint_match_threshold`, `local_fingerprint_partial_min_margin`, `registry_confidence`, and runtime `min_confidence` take precedence where applicable.

The policy is deliberately conservative: a partial match without a measurable runner-up margin is `REVIEW`, and an online result that was not learned is normally `REVIEW` rather than an automatic match.
