# Smart Music Organizer v9.2

Smart Music Organizer v9.2 is a crash-safe music-library organizer with identity-first artist resolution, Album-aware foldering, deterministic collaboration filenames, and AcoustID fallback.

The default output is now:

```text
Music Library/
└── primary_artist/
    ├── Album Name/
    │   ├── Song 1 - Primary Artist.mp3
    │   └── Duet - Primary Artist (Guest Artist).mp3
    └── _Singles/
        └── Standalone Song - Primary Artist.mp3
```

## Folder policy

- The primary performer owns the top-level Artist folder.
- Album Artist, track credits, existing tags, provider identities, and whole-library statistics are used to choose that primary performer.
- Collaborators do not create separate Artist folders.
- Album names create the second folder level.
- Tracks with no reliable album name are placed in `_Singles`.
- Filenames use `Title - Primary Artist (Guests).ext`.
- Artist folder names use lowercase `snake_case` by default.
- Album names remain human-readable and are sanitized for Windows paths.

Example:

```text
alireza_ghorbani/
├── Iran, My Land/
│   ├── Track One - Alireza Ghorbani.mp3
│   └── Duet - Alireza Ghorbani (Guest Singer).mp3
└── _Singles/
    └── Standalone Track - Alireza Ghorbani.mp3
```

## Configuration

Album folders are enabled by default:

```json
{
  "album_subfolders_enabled": true,
  "singles_folder": "_Singles",
  "artist_folder_name_style": "snake_case",
  "filename_artist_credit_style": "primary_with_guests_parentheses",
  "filename_guest_separator": " x "
}
```

To restore the flat Artist-only layout, set:

```json
{
  "album_subfolders_enabled": false
}
```

## Identification priority

1. Embedded MusicBrainz IDs and ISRC
2. Chromaprint / AcoustID fingerprint
3. Agreement between MusicBrainz, Spotify, and Apple catalog results
4. Track Artist and Album Artist structure
5. Existing tags and filename parsing
6. Lyrics only as a manual-review clue

Lyrics are not used as the primary automatic identity key because covers and alternate performances may share the same words.

## Running

Preview without moving files:

```powershell
.\run_preview.bat
```

Apply the approved plan:

```powershell
.\run_apply.bat
```

Reconfigure options:

```powershell
.\reconfigure.bat
```

The organizer keeps collision and duplicate protection enabled and does not silently overwrite existing files.
