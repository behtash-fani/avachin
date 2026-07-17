@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Run setup.bat first.
  exit /b 2
)
.venv\Scripts\python.exe tools\enrich_registry_with_spotify.py --in-place
pause
