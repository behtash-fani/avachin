# Avachin Windows Preview GUI

Avachin v12.10 includes the first Windows desktop shell. It is deliberately
Preview-only and consumes the existing Status and Operation APIs instead of
reimplementing recognition, fingerprinting, metadata or file-management logic.

## Start

```powershell
scripts\windows\gui_preview.bat
```

Optional initial folder:

```powershell
scripts\windows\gui_preview.bat --folder "D:\Music"
```

The GUI defaults to offline mode. Online providers can be allowed explicitly:

```powershell
scripts\windows\gui_preview.bat --online
```

## Included in the MVP

- secret-free runtime status for fpcalc, FFmpeg, the local fingerprint database
  and AudD budget;
- folder selection;
- organizer Preview in the isolated child process;
- live phase/progress/log events;
- cooperative Cancel using the public Operation API;
- links to JSON, CSV and other report artifacts;
- safe close behavior while Preview is running.

## Deliberate limitations

- no Apply button or Apply request;
- no direct SQLite access from the GUI;
- no recognition or metadata policy inside the UI;
- no manual Review approval yet;
- no installer yet.

Apply, Review approval and Undo belong to the later GUI safety phase after the
Preview shell is accepted on Windows and the review/revoke workflows are proven.
