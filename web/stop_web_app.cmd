@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_web_app.ps1" %*
pause
