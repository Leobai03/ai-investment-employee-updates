@echo off
setlocal
chcp 65001 > nul
set "PRODUCT_DIR=%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PRODUCT_DIR%scripts\windows\start.ps1" -NoBrowser
if errorlevel 1 exit /b 1
"%SystemRoot%\explorer.exe" "http://127.0.0.1:8765"
exit /b 0
