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

echo.
echo Avachin - BULK LOCAL INDEX PREVIEW
echo.
echo This scans an already-organized MP3 library and reports files with
echo trustworthy Title and Artist tags. No fingerprint is stored and no music
echo file is changed.
echo Decoder-damaged files can use a validated temporary analysis copy during Apply.
echo.

if not "%~1"=="" (
    py tools\avachin_bulk_index.py --root "%~1"
) else (
    py tools\avachin_bulk_index.py
)
set EXIT_CODE=%ERRORLEVEL%

echo.
pause
exit /b %EXIT_CODE%
