@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

echo.
echo Avachin full benchmark - Preview only, offline by default
echo.
py tools\run_benchmark_pipeline.py %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if "%EXIT_CODE%"=="0" (
    echo Benchmark gate passed: False Auto-Apply is zero.
) else if "%EXIT_CODE%"=="2" (
    echo Benchmark completed, but the False Auto-Apply gate failed.
    echo Review reports\benchmark\run-*\pipeline-report.json
) else (
    echo Benchmark pipeline failed with exit code %EXIT_CODE%.
)
exit /b %EXIT_CODE%
