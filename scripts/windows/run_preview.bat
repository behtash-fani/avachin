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
echo Avachin v12.0 - LOCAL-FIRST PARTIAL-AUDIO PREVIEW
echo Select the ROOT of your complete music library.
echo.
echo This run performs identification and planning, then writes a report.
echo Full tracks and mid-song clips are checked against the local database first.
echo Trusted online results for uncertain files are saved and segment-indexed locally.
echo AcoustID and AudD are used only when the audio is still unknown locally.
echo Real AudD requests are protected by the local request budget.
echo No music file will be changed.
echo.
py tools\avachin_partial_fingerprint_launcher.py
set EXIT_CODE=%ERRORLEVEL%

echo.
if "%EXIT_CODE%"=="0" (
    echo ============================================================
    echo Local fingerprint summary from the latest preview report
    echo ============================================================
    py tools\summarize_preview_fingerprints.py
    echo.
)

pause
exit /b %EXIT_CODE%
