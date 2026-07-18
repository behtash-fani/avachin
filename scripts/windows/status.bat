@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

echo.
echo Avachin v12.2 - RUNTIME STATUS
echo.
py tools\avachin_status.py
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
