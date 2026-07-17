@echo off
setlocal
if defined LOCALAPPDATA (
    explorer "%LOCALAPPDATA%\SmartMusicOrganizer\reports"
) else (
    echo Reports are stored in the SmartMusicOrganizer application data folder.
    pause
)
