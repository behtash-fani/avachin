@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

set "SOURCE_FILE=%~1"
if not defined SOURCE_FILE set "SOURCE_FILE=C:\Users\behtash\Music\Siavash Ghomayshi\Singles\Baazi - Siavash Ghomayshi.mp3"

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
    if errorlevel 1 exit /b 1
)

echo.
echo Creating an isolated metadata-free Avachin test copy.
echo The original file will not be changed.
echo.
py tools\create_unknown_test_copy.py --source "%SOURCE_FILE%" --output-dir "C:\Avachin_Test" --force
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
    echo Next: run scripts\windows\run_preview.bat and select C:\Avachin_Test
)
pause
exit /b %EXIT_CODE%
