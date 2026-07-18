@echo off
setlocal
cd /d "%~dp0\..\.."

echo.
echo Avachin - AudD local request budget
echo.
echo This is Avachin's local safety counter. It does not query or modify
echo the AudD dashboard and never prints the API token.
echo.

py tools\audd_usage_guard.py --limit 300 --budget-id manual-300 status

echo.
echo To reset only after confirming the dashboard allowance renewed:
echo py tools\audd_usage_guard.py --limit 300 --budget-id manual-300 reset --confirm RESET
echo.
pause
