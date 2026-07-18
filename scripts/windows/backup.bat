@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

echo.
echo Avachin one-command backup
echo.
py tools\avachin_backup.py backup %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
    echo Backup failed with exit code %EXIT_CODE%.
) else (
    echo Backup completed successfully.
)
exit /b %EXIT_CODE%
