@echo off
REM Double-click to stage and commit auto_Interner. Never pushes.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0commit-ready.ps1"
echo.
pause
