@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0"

echo Installing Python dependencies...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed.
    pause
    exit /b 1
)

echo.
echo Installing optional Chromaprint fpcalc for audio fingerprints...
py setup_fpcalc.py
if errorlevel 1 (
    echo WARNING: fpcalc installation failed. The organizer will still work,
    echo but AcoustID identification and audio-equivalent duplicate detection
    echo will remain disabled until fpcalc is installed.
)

echo.
py configure.py
if errorlevel 1 exit /b 1

echo.
echo Setup completed.
pause
