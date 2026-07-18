@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
)

echo.
echo Avachin - BULK LOCAL INDEX APPLY
echo.
echo This creates a timestamped SQLite backup, then fingerprints only MP3 files
echo with trustworthy Title and Artist tags. Identical audio is skipped.
echo Decoder-damaged files may use a validated temporary re-encoded copy.
echo The original music files are never renamed, moved, retagged, or modified.
echo.

if not "%~1"=="" (
    py tools\avachin_resilient_bulk_index_launcher.py --root "%~1" --apply
) else (
    py tools\avachin_resilient_bulk_index_launcher.py --apply
)
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" echo Finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
