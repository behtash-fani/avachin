@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

for /f "delims=" %%V in ('py -c "from tools.version import AVACHIN_VERSION; print(AVACHIN_VERSION)"') do set AVACHIN_VERSION=%%V

echo.
echo Avachin v%AVACHIN_VERSION% - RUNTIME STATUS
echo.
py tools\avachin_status.py
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
