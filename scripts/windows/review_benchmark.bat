@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

for /f %%V in ('py -c "from tools.version import AVACHIN_VERSION; print(AVACHIN_VERSION)"') do set AVACHIN_VERSION=%%V

echo.
echo Avachin v%AVACHIN_VERSION% benchmark review - no audio regeneration

echo.
py tools\benchmark_review.py %*
exit /b %ERRORLEVEL%
