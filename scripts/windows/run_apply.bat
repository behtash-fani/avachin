@echo off
chcp 65001 >nul
setlocal
set PYTHONUTF8=1
cd /d "%~dp0..\.."

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Running setup.
    call "%~dp0setup.bat"
)

if not exist "config.json" (
    py configure.py
)

echo.
echo Avachin v11.7 - LOCAL-FIRST SAFE APPLY MODE
echo Select the ROOT of your complete music library.
echo.
echo The program will:
echo   1. Check the local fingerprint database before every online provider
echo   2. Identify all tracks first
echo   3. Build the final Artist\Album structure
echo   4. Use crash-safe transactions and a live journal
echo   5. Keep cover/lyrics/cue/playlist sidecars with albums
echo   6. Create a complete undo manifest outside the library
echo   7. Use AcoustID and AudD only for tracks still unknown locally
echo.
echo No per-file confirmation will be requested.
echo.
py tools\avachin_local_first_launcher.py --apply
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo Finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
