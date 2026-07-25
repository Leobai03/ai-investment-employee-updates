@echo off
chcp 65001 > nul
title AI投研数字员工 - 停止
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\stop.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%

