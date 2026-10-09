@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance.ps1 -Command backup
exit /b %ERRORLEVEL%
