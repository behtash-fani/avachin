@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set PYTHONUTF8=1
cd /d "%~dp0..\.."

py -m pip show mutagen >nul 2>&1
if errorlevel 1 (
    echo وابستگی‌های آواچین نصب نیستند. در حال اجرای راه‌اندازی اولیه...
    call "%~dp0setup.bat"
    if errorlevel 1 (
        echo راه‌اندازی اولیه ناموفق بود.
        pause
        exit /b 1
    )
)

for /f %%V in ('py -c "from tools.version import AVACHIN_VERSION; print(AVACHIN_VERSION)"') do set AVACHIN_VERSION=%%V

echo.
echo آواچین نسخه %AVACHIN_VERSION%
echo رابط فارسی راست‌چین در حال اجراست...
echo در نسخه اولیه، مرتب‌سازی فایل‌ها فقط در حالت پیش‌نمایش اجرا می‌شود.
echo.
py tools\avachin_user_app.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
