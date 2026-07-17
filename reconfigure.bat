@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
py configure.py
pause
