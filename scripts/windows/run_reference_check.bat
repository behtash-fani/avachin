@echo off
setlocal
cd /d "%~dp0..\.."
python tools\validate_reference_data.py
pause

