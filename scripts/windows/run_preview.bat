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
echo Avachin v11.7 - LOCAL-FIRST PREVIEW MODE
echo Select the ROOT of your complete music library.
echo.
echo This run performs identification and planning, then writes a report.
echo The local fingerprint database is checked before every online provider.
echo AcoustID and AudD are used only when the track is still unknown locally.
echo No file will be changed.
echo.
py tools\avachin_local_first_launcher.py
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
