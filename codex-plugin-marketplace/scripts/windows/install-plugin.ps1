$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$marketplaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Get-CodexCommand {
    if ($env:APPDATA) {
        $npmCodex = Join-Path $env:APPDATA "npm\codex.cmd"
        if (Test-Path -LiteralPath $npmCodex) {
            return $npmCodex
        }
    }
    foreach ($name in @("codex.exe", "codex.cmd", "codex")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    return ""
}

Write-Host ""
Write-Host "AI 投研数字员工｜安装 Codex 插件" -ForegroundColor Cyan
Write-Host "--------------------------------"

$codex = Get-CodexCommand
if (-not $codex) {
    throw "没有找到 Codex CLI。请先双击 product\Windows_首次配置.cmd。"
}

Write-Host "正在添加本地插件源……"
& $codex plugin marketplace add $marketplaceRoot
if ($LASTEXITCODE -ne 0) {
    Write-Warning "插件源可能已经添加；继续检查插件安装。"
}

Write-Host "正在安装 AI 投研数字员工……"
$installedPlugins = (& $codex plugin list --json 2>&1 | Out-String)
if ($installedPlugins -notmatch "ai-investment-employee") {
    & $codex plugin add "ai-investment-employee@boss-investment"
    if ($LASTEXITCODE -ne 0) {
        throw "插件安装没有完成。请保留窗口内容并联系交付人员。"
    }
}

Write-Host ""
Write-Host "插件安装完成。" -ForegroundColor Green
Write-Host "请重新打开 ChatGPT/Codex，用 Codex 打开 product 文件夹。"
Write-Host "然后输入：请使用 `$ai-investment-employee 作为我的投研数字员工。"
