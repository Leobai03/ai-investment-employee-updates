@echo off
chcp 65001 > nul
title AI投研数字员工 - Windows 首次配置
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\setup.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo 配置没有完成，请保留本窗口内容并联系交付人员。
pause
exit /b %RESULT%

