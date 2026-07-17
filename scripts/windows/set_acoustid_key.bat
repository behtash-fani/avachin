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
set "ACOUSTID_API_KEY=%KEY%"

py -c "import json; payload={'acoustid_api_key':'%KEY%','acoustid_api_key_env':'ACOUSTID_API_KEY','online_providers':{'acoustid':True},'fingerprint_identification_enabled':True,'fingerprint_when_uncertain':True,'fingerprint_min_score':0.72}; open('config.local.json','w',encoding='utf-8').write(json.dumps(payload, ensure_ascii=False, indent=2))"
if errorlevel 1 (
  echo Could not write config.local.json.
  exit /b 1
)

echo.
echo AcoustID key is now active for Avachin.
echo It was saved to your Windows user environment and to ignored local file config.local.json.
echo No API key was written into Git-tracked files.
endlocal
