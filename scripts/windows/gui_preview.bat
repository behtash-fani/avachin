@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

for /f %%V in ('py -c "from tools.version import AVACHIN_VERSION; print(AVACHIN_VERSION)"') do set AVACHIN_VERSION=%%V

echo Starting Avachin v%AVACHIN_VERSION% Preview GUI...
py tools\avachin_gui.py %*
exit /b %ERRORLEVEL%
