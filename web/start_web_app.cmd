@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_web_app.ps1" %*
pause
