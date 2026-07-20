@echo off
chcp 65001 >nul
call "%~dp0scripts\windows\avachin.bat" %*
exit /b %ERRORLEVEL%
