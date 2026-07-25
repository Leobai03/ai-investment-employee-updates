@echo off
chcp 65001 > nul
title AI投研数字员工 - 演示模式
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start.ps1" -Demo
if errorlevel 1 pause

