# Review Center online identification

Avachin v12.12 can ask online providers for the identity of a real `REVIEW` or `REJECT` file without learning or changing anything automatically.

## Safety rules

- Generated files under `benchmark/generated` are never sent to an online provider.
- Automatic report discovery ignores `reports/benchmark` and selects the newest real Preview DetectionResult report.
- AcoustID is tried first when its key and `fpcalc` are available.
- MusicBrainz, Apple and optional Spotify are used only when existing tags, folder names or the filename provide a meaningful Artist and Title hint.
- AudD is the final acoustic fallback. Real AudD requests continue to use the persistent fail-closed local budget guard; cache hits do not consume the counter.
- Provider output is a suggestion only. It fills the verification form but does not write to the local fingerprint database.
- The user must listen to the file and press **Apply verified identity** before the audited Review Center learns it.
- Confirmed learning creates a SQLite backup, audit entry and Undo action. The MP3 is not moved, renamed, retagged, replaced or deleted.

## Windows workflow

```powershell
.\scripts\windows\review_center.bat
```

1. Open the **Review Queue** tab.
2. Select a real unresolved file.
3. Use **Identify selected online**, or use **Identify all real items online** for the complete real queue.
4. Listen to every proposed match.
5. Correct Artist, Title or Album if necessary.
6. Press **Apply verified identity** only after verification.
7. Use **Audit & Undo** to reverse a confirmed learning action.

A warning is shown when a benchmark report is selected manually, and online actions remain disabled for its generated samples.
