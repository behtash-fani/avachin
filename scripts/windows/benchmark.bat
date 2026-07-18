@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

if "%~1"=="" (
    echo Usage:
    echo   benchmark.bat bootstrap
    echo   benchmark.bat validate
    echo   benchmark.bat generate --plan-only
    echo   benchmark.bat generate
    echo   benchmark.bat evaluate --detection-report "C:\path\detection-report.json" --corpus-root "C:\path\benchmark"
    echo   benchmark.bat calibrate
    exit /b 2
)

py tools\avachin_benchmark.py %*
exit /b %ERRORLEVEL%
