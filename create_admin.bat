@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance.ps1 -Command admin
set "ADMIN_EXIT_CODE=%ERRORLEVEL%"
if "%ADMIN_EXIT_CODE%"=="0" (
    echo Administrator creation confirmed. Open http://127.0.0.1:3000/login
) else (
    echo Administrator was NOT created. Read the error above; no existing password was changed.
)
pause
exit /b %ADMIN_EXIT_CODE%
