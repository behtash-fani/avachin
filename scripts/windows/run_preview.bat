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

if not exist "config.json" (
    py configure.py
)

echo.
echo Smart Music Organizer v8 - PREVIEW MODE
echo Select the ROOT of your complete music library.
echo.
echo This run performs identification and planning, then writes a report.
echo No file will be changed.
echo.
py smart_music_organizer.py
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%

