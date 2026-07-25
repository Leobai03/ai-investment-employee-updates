. (Join-Path $PSScriptRoot "Common.ps1")

Write-Section "天策 AI 投研数字员工｜卸载 Windows 开机自启"
if (Test-Path -LiteralPath $script:StartupShortcut) {
    Remove-Item -LiteralPath $script:StartupShortcut -Force
    Write-Host "已删除当前 Windows 用户的开机启动快捷方式。" -ForegroundColor Green
} else {
    Write-Host "没有发现开机自启配置。"
}
$stopped = Stop-ResearchDesk -IncludeSupervisor
if ($stopped) {
    Write-Host "后台研究台已停止。"
}
Write-Host "老板偏好、对话、报告和数据库均保留，没有删除。"

