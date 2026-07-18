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
echo Avachin v12.1 - LOCAL-FIRST SAFE APPLY
echo Select the ROOT of your complete music library.
echo.
echo The program will:
echo   1. Check full tracks and mid-song clips against the local database first
echo   2. Use validated temporary analysis copies for decoder-damaged audio
echo   3. Save and segment-index trusted online results locally
echo   4. Identify all tracks before changing the library
echo   5. Build the final Artist\Album structure
echo   6. Use crash-safe transactions and a live journal
echo   7. Keep cover, lyrics, cue, and playlist sidecars with albums
echo   8. Create a complete undo manifest outside the library
echo   9. Use AcoustID and AudD only for audio still unknown locally
echo  10. Protect real AudD requests with the local request budget
echo.
echo No per-file confirmation will be requested.
echo.
py tools\avachin_runtime.py --apply
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo Finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
