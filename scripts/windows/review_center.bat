@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
    if errorlevel 1 exit /b 1
)

echo.
echo Avachin Review Center - backup, audit, undo, online suggestions and artist aliases
echo Clipboard paste and right-click menu enabled.
echo Artist Alias Manager is local-only and consumes zero AudD requests.
echo Alias consolidation changes only the local fingerprint database; MP3 folders are Preview-only.
echo Online results are suggestions only; no identity is learned without confirmation.
echo No music file will be moved, renamed, retagged or deleted.
echo.
py tools\avachin_review_alias_gui.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
