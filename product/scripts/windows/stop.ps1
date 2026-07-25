. (Join-Path $PSScriptRoot "Common.ps1")

Write-Section "天策 AI 投研数字员工｜Windows 停止"
$stopped = Stop-ResearchDesk -IncludeSupervisor
if ($stopped) {
    Write-Host "研究台和后台守护已停止。" -ForegroundColor Green
} else {
    Write-Host "研究台当前没有运行。"
}
if (Test-Path -LiteralPath $script:StartupShortcut) {
    Write-Host "注意：开机自启仍然保留，下次登录 Windows 时会重新启动。" -ForegroundColor Yellow
    Write-Host "如需彻底关闭，请双击「Windows_卸载开机自启.cmd」。"
}
