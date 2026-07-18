@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

if "%~1"=="" (
    echo Usage: restore_dry_run.bat "C:\path\to\avachin-backup.zip"
    exit /b 2
)

echo.
echo Avachin restore validation - DRY RUN ONLY
echo Archive: %~1
echo.
py tools\avachin_backup.py restore "%~1" --dry-run
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
    echo Restore dry-run failed with exit code %EXIT_CODE%.
) else (
    echo Restore dry-run completed. No files were changed.
)
exit /b %EXIT_CODE%
