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
echo Avachin v11.4 - SAFE COPY MODE
echo The output folder must be separate from and NOT inside the input library.
echo AcoustID fingerprint recognition is used when ACOUSTID_API_KEY is set.
echo.
set /p INPUT_FOLDER=Input music library root: 
set /p OUTPUT_FOLDER=New organized library root: 
if "%INPUT_FOLDER%"=="" exit /b 2
if "%OUTPUT_FOLDER%"=="" exit /b 2

echo.
py tools\avachin_launcher.py ^
  --folder "%INPUT_FOLDER%" ^
  --copy-to "%OUTPUT_FOLDER%"
set EXIT_CODE=%ERRORLEVEL%
echo.
if not "%EXIT_CODE%"=="0" echo Finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
