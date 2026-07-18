@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

echo.
echo Avachin acceptance baseline
echo.
py tools\run_acceptance.py %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if not "%EXIT_CODE%"=="0" (
    echo Acceptance failed with exit code %EXIT_CODE%.
) else (
    echo Acceptance completed successfully.
)
exit /b %EXIT_CODE%
