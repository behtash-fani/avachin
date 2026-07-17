@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

set "AUDIO_FILE=%~1"
if not defined AUDIO_FILE (
  set /p "AUDIO_FILE=MP3 file path: "
)

rem Accept pasted paths with or without surrounding quotes.
set "AUDIO_FILE=!AUDIO_FILE:"=!"

if not defined AUDIO_FILE (
  echo No file selected.
  exit /b 2
)

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
    if errorlevel 1 exit /b 1
)

if not exist "config.json" (
    py configure.py
    if errorlevel 1 exit /b 1
)

echo.
echo Avachin - AcoustID single-file diagnostic
echo This does not rename, move, or modify the file.
echo File: !AUDIO_FILE!
echo.
py tools\diagnose_fingerprint.py --file "!AUDIO_FILE!"
set "EXIT_CODE=!ERRORLEVEL!"
echo.
pause
exit /b !EXIT_CODE!
