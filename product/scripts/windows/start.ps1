param(
    [switch]$NoBrowser,
    [switch]$Demo
)
. (Join-Path $PSScriptRoot "Common.ps1")

Write-Section "天策 AI 投研数字员工｜Windows 启动"
Start-ResearchDesk -Demo:$Demo -NoBrowser:$NoBrowser

