@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0..\.."

set "KEY=%~1"
if "%KEY%"=="" (
  set /p KEY=Enter AudD API token: 
)

if "%KEY%"=="" (
  echo No token entered.
  exit /b 1
)

setx AUDD_API_TOKEN "%KEY%" >nul
set "AUDD_API_TOKEN=%KEY%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$path='config.local.json'; if (Test-Path -LiteralPath $path) { try { $payload = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $payload = [pscustomobject]@{} } } else { $payload = [pscustomobject]@{} }; if ($null -eq $payload.online_providers) { $payload | Add-Member -NotePropertyName online_providers -NotePropertyValue ([pscustomobject]@{}) -Force }; $payload | Add-Member -NotePropertyName audd_api_token -NotePropertyValue $env:AUDD_API_TOKEN -Force; $payload | Add-Member -NotePropertyName audd_api_token_env -NotePropertyValue 'AUDD_API_TOKEN' -Force; $payload | Add-Member -NotePropertyName audio_recognition_fallbacks_enabled -NotePropertyValue $true -Force; $payload | Add-Member -NotePropertyName audd_cache_days -NotePropertyValue 30 -Force; $payload.online_providers | Add-Member -NotePropertyName audd -NotePropertyValue $true -Force; $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $path -Encoding UTF8"
if errorlevel 1 (
  echo Could not update config.local.json.
  exit /b 1
)

echo.
echo AudD token is now active for Avachin.
echo It was saved to your Windows user environment and to ignored local file config.local.json.
echo No API token was written into Git-tracked files.
endlocal
