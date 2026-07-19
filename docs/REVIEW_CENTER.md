# Avachin Review Center

Avachin v12.11 adds an audited correction workflow before GUI Apply is enabled.

## Launch on Windows

```powershell
scripts\windows\review_center.bat
```

The Review Center has three surfaces:

1. **Review Queue** reads the newest `detection-report.json` and shows `REVIEW`, `REJECT`, or otherwise unsafe results.
2. **Local Database** searches recordings and physical audio encodings, then supports audio reassignment, recording revoke, and duplicate merge.
3. **Audit & Undo** shows every human change and can undo the latest or a selected applied action.

## Safety contract

Every write operation:

- creates a consistent SQLite backup under the local app-data `review_backups` directory;
- records reviewer, reason, old identity, new identity, affected IDs and timestamp;
- changes only the local fingerprint database;
- never renames, moves, retags, replaces or deletes an MP3;
- is reversible from the Audit & Undo tab.

## Supported operations

### Correct one physical audio association

Select a recording, select one audio encoding, enter the verified artist/title/album, and choose **Reassign audio**. Full fingerprints and derived partial-fingerprint segments move together.

### Learn a previously rejected file

Select a `REJECT` item, play it, enter the verified identity, and choose **Apply verified identity**. The Review Center fingerprints the file, stores the verified recording, builds partial segments, and writes an undoable audit record.

### Revoke a wrong recording

Revoke changes the recording status to `revoked`, so full matches ignore it. Derived segment rows are neutralized as well, so a short clip cannot continue matching a revoked identity. Undo restores the status and rebuilds the segment index.

### Merge duplicate recordings

Select the duplicate source recording and enter the target recording ID. Audio encodings, full fingerprints, partial segments and external IDs move to the target; the source is retained with `merged` status for audit and Undo.

## CLI

```powershell
py tools\avachin_review.py queue
py tools\avachin_review.py search Faded
py tools\avachin_review.py detail <recording-id>
py tools\avachin_review.py reassign --audio-file-id 123 --artist Shahrokh --title Pedar --album Singles
py tools\avachin_review.py learn --file "C:\Music\Unknown.mp3" --artist "Artist" --title "Title"
py tools\avachin_review.py revoke <recording-id>
py tools\avachin_review.py merge --source <wrong-id> --target <correct-id>
py tools\avachin_review.py history
py tools\avachin_review.py undo
```

## Current product boundary

Review Center does not expose organizer Apply. The next product gate is a successful Windows smoke test of correction and Undo, followed by Apply/rollback testing in a sandbox copy of a music folder.
