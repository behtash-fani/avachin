@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

set "SOURCE_FILE=%~1"
if not defined SOURCE_FILE set "SOURCE_FILE=C:\Users\behtash\Music\Alan Walker\Singles\Faded - Alan Walker.mp3"

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
    if errorlevel 1 exit /b 1
)

echo.
echo Creating a 20-second metadata-free clip from the middle of the song.
echo The original file will not be changed.
echo.
py tools\create_mid_song_test_clip.py --source "%SOURCE_FILE%" --output-dir "C:\Avachin_Clip_Test" --start 60 --duration 20 --force
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
    echo Next: run scripts\windows\run_preview.bat and select C:\Avachin_Clip_Test
)
pause
exit /b %EXIT_CODE%
