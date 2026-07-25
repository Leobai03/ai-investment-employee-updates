@echo off
chcp 65001 > nul
title AI投研数字员工 - 检查并安装更新
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\update.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %RESULT%

