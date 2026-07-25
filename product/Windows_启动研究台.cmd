@echo off
chcp 65001 > nul
title AI投研数字员工 - 启动
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请双击“Windows_查看运行日志.cmd”。
  pause
  exit /b 1
)

