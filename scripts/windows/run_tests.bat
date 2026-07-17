@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."
py -m unittest discover -s tests -v
set EXIT_CODE=%ERRORLEVEL%
echo.
pause
exit /b %EXIT_CODE%

