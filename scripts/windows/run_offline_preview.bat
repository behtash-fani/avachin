@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

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
echo Avachin v11.4 - FAST OFFLINE PREVIEW
echo Existing tags and filenames are used. No catalog or AcoustID requests are made.
echo.
py tools\avachin_launcher.py --offline
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%
