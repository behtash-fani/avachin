@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"

set "MANIFEST=%~1"
if "%MANIFEST%"=="" (
    echo Paste the full path to a changes.json undo manifest.
    set /p MANIFEST=Manifest path: 
)
if "%MANIFEST%"=="" exit /b 2

py smart_music_organizer.py --undo "%MANIFEST%"
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%
