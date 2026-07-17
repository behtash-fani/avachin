@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0..\.."

set "KEY=%~1"
if "%KEY%"=="" (
  set /p KEY=Enter AcoustID API key: 
)

if "%KEY%"=="" (
  echo No key entered.
  exit /b 1
)

setx ACOUSTID_API_KEY "%KEY%" >nul

echo.
echo AcoustID key was saved to your Windows user environment as ACOUSTID_API_KEY.
echo Restart PowerShell or Command Prompt before running Avachin.
echo No API key was written into Git-tracked files.
endlocal
