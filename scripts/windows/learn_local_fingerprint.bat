@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

set "AUDIO_FILE=%~1"
set "ARTIST=%~2"
set "TITLE=%~3"
set "ALBUM=%~4"

if not defined AUDIO_FILE (
  set /p "AUDIO_FILE=Correct MP3 file path: "
)
if not defined ARTIST (
  set /p "ARTIST=Artist: "
)
if not defined TITLE (
  set /p "TITLE=Title: "
)
if not defined ALBUM (
  set /p "ALBUM=Album optional: "
)

rem Accept pasted paths with or without surrounding quotes.
set "AUDIO_FILE=!AUDIO_FILE:"=!"

if not defined AUDIO_FILE (
  echo No file selected.
  exit /b 2
)
if not defined ARTIST (
  echo Artist is required.
  exit /b 2
)
if not defined TITLE (
  echo Title is required.
  exit /b 2
)

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
    if errorlevel 1 exit /b 1
)

echo.
echo Avachin - learn one local fingerprint
echo This does not move, rename, or modify the audio file.
echo File: !AUDIO_FILE!
echo.

py tools\local_fingerprint_library.py learn --file "!AUDIO_FILE!" --artist "!ARTIST!" --title "!TITLE!" --album "!ALBUM!" --source manual
set "EXIT_CODE=!ERRORLEVEL!"
echo.
pause
exit /b !EXIT_CODE!
